from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone

import pytest

from local_tracker.models import AppData
from local_tracker.service import TrackerError, TrackerService
from local_tracker.storage import JsonStore, StorageError


@pytest.fixture
def service(tmp_path) -> TrackerService:
    return TrackerService(JsonStore(tmp_path / "data.json"))


def test_project_task_and_timer_flow(service: TrackerService) -> None:
    project = service.add_project("Personal", "#7c6ff0")
    task = service.add_task("Write notes", project.id)

    entry = service.start(task.id, "Morning session")
    assert service.active_entry == entry
    service.stop(datetime.now(timezone.utc) + timedelta(seconds=5))

    assert service.active_entry is None
    assert entry.duration_seconds() >= 4
    assert service.store.load().entries[0].note == "Morning session"


def test_only_one_timer_can_run(service: TrackerService) -> None:
    project = service.add_project("Personal", "#7c6ff0")
    first = service.add_task("First", project.id)
    second = service.add_task("Second", project.id)
    service.start(first.id)

    with pytest.raises(TrackerError, match="already running"):
        service.start(second.id)


def test_referenced_items_are_archived(service: TrackerService) -> None:
    project = service.add_project("Client", "#3d8bfd")
    task = service.add_task("Review", project.id)
    service.start(task.id)
    service.stop(datetime.now(timezone.utc) + timedelta(seconds=1))

    assert service.remove_task(task.id) is False
    assert task.archived is True
    assert service.remove_project(project.id) is False
    assert project.archived is True
    assert service.data.entries[0].project_name == "Client"


def test_report_groups_entries(service: TrackerService) -> None:
    project = service.add_project("Build", "#40c057")
    task = service.add_task("Code", project.id)
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    entry = service.start(task.id)
    service.update_entry(
        entry.id,
        task.id,
        "",
        start,
        start + timedelta(minutes=25),
    )

    total, projects = service.report_totals(date.today(), date.today())
    assert total == 25 * 60
    assert projects[("Build", "#40c057")] == 25 * 60


def test_daily_total_counts_only_time_overlapping_that_day(
    service: TrackerService,
) -> None:
    project = service.add_project("Night work", "#7c6ff0")
    task = service.add_task("Deploy", project.id)
    day = date(2026, 8, 24)
    day_start = datetime.combine(day, time.min).astimezone(timezone.utc)
    entry = service.start(task.id)
    service.update_entry(
        entry.id,
        task.id,
        "",
        day_start - timedelta(minutes=30),
        day_start + timedelta(hours=1),
    )

    assert service.total_for_day(day) == 60 * 60
    assert service.daily_project_totals(day, day) == {
        day: {("Night work", "#7c6ff0"): 60 * 60}
    }


def test_store_recovers_from_backup(tmp_path) -> None:
    path = tmp_path / "data.json"
    store = JsonStore(path)
    store.save(AppData())
    store.save(AppData())
    path.write_text("{broken", encoding="utf-8")

    recovered = store.load()

    assert recovered == AppData()
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_store_raises_if_primary_and_backup_are_invalid(tmp_path) -> None:
    path = tmp_path / "data.json"
    path.write_text("bad", encoding="utf-8")
    path.with_suffix(".backup.json").write_text("also bad", encoding="utf-8")

    with pytest.raises(StorageError):
        JsonStore(path).load()


def test_store_recovers_from_external_history_after_data_removal(tmp_path) -> None:
    path = tmp_path / "sandbox" / "data.json"
    history = tmp_path / "external-history"
    store = JsonStore(path, history_path=history)
    data = AppData()
    data.projects.append(service_project := service_project_factory())
    store.save(data)
    path.unlink()

    recovered = JsonStore(path, history_path=history).load()

    assert recovered.projects[0].id == service_project.id
    assert path.exists()


def test_snapshot_history_is_rotated(tmp_path) -> None:
    path = tmp_path / "data.json"
    history = tmp_path / "history"
    store = JsonStore(path, history_path=history, history_limit=2)

    for index in range(4):
        data = AppData(schema_version=1)
        data.projects.append(service_project_factory(f"Project {index}"))
        store.save(data)

    assert len(list(history.glob("data-*.json"))) == 2


def service_project_factory(name: str = "Recovered"):
    from local_tracker.models import Project

    return Project(name=name)
