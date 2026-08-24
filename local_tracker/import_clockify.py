from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import Project, Task, TimeEntry, to_iso
from .storage import JsonStore

PROJECT_COLORS = (
    "#7c6ff0",
    "#3d8bfd",
    "#22b8cf",
    "#40c057",
    "#fab005",
    "#fd7e14",
    "#e64980",
    "#ef476f",
)


@dataclass(slots=True)
class ImportResult:
    imported_entries: int = 0
    skipped_duplicates: int = 0
    created_projects: int = 0
    created_tasks: int = 0


def normalize_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def parse_local_datetime(date_value: str, time_value: str) -> datetime:
    value = datetime.strptime(
        f"{date_value.strip()} {time_value.strip()}",
        "%d/%m/%Y %H:%M:%S",
    )
    return value.astimezone()


def import_clockify_csv(csv_path: Path, store: JsonStore) -> ImportResult:
    data = store.load()
    result = ImportResult()
    projects = {normalize_name(project.name): project for project in data.projects}
    tasks = {(task.project_id, normalize_name(task.name)): task for task in data.tasks}
    existing_entries = {
        (
            normalize_name(entry.project_name),
            normalize_name(entry.task_name),
            entry.start_at,
            entry.end_at,
        )
        for entry in data.entries
    }

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            project_name = row.get("Project", "").strip() or "No project"
            task_name = (
                row.get("Description", "").strip()
                or row.get("Task", "").strip()
                or "Untitled task"
            )
            try:
                start = parse_local_datetime(row["Start Date"], row["Start Time"])
                end = parse_local_datetime(row["End Date"], row["End Time"])
            except (KeyError, ValueError) as error:
                raise ValueError(
                    f"Invalid Clockify row {row_number}: {error}"
                ) from error
            if end <= start:
                raise ValueError(
                    f"Invalid Clockify row {row_number}: end must be after start"
                )

            project_key = normalize_name(project_name)
            project = projects.get(project_key)
            if project is None:
                color_index = sum(project_key.encode("utf-8")) % len(PROJECT_COLORS)
                project = Project(
                    name=project_name,
                    color=PROJECT_COLORS[color_index],
                )
                data.projects.append(project)
                projects[project_key] = project
                result.created_projects += 1
            elif project.archived:
                project.archived = False

            task_key = (project.id, normalize_name(task_name))
            task = tasks.get(task_key)
            if task is None:
                task = Task(name=task_name, project_id=project.id)
                data.tasks.append(task)
                tasks[task_key] = task
                result.created_tasks += 1
            elif task.archived:
                task.archived = False

            start_at = to_iso(start)
            end_at = to_iso(end)
            entry_key = (project_key, normalize_name(task_name), start_at, end_at)
            if entry_key in existing_entries:
                result.skipped_duplicates += 1
                continue

            data.entries.append(
                TimeEntry(
                    task_id=task.id,
                    task_name=task.name,
                    project_id=project.id,
                    project_name=project.name,
                    project_color=project.color,
                    note="",
                    start_at=start_at,
                    end_at=end_at,
                )
            )
            existing_entries.add(entry_key)
            result.imported_entries += 1

    data.entries.sort(key=lambda entry: entry.start_at)
    # Save the untouched on-disk state first so recovery history contains an
    # explicit pre-import restore point.
    store.save(store.load())
    store.save(data)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a Clockify detailed CSV")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--data-path", required=True, type=Path)
    parser.add_argument("--backup-dir", required=True, type=Path)
    arguments = parser.parse_args()
    result = import_clockify_csv(
        arguments.csv_path,
        JsonStore(arguments.data_path, history_path=arguments.backup_dir),
    )
    print(
        f"Imported {result.imported_entries} entries; "
        f"skipped {result.skipped_duplicates} duplicates; "
        f"created {result.created_projects} projects and "
        f"{result.created_tasks} tasks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
