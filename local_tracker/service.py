from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable

from .models import AppData, Project, Task, TimeEntry, to_iso, utc_now
from .storage import JsonStore


class TrackerError(ValueError):
    pass


class TrackerService:
    def __init__(self, store: JsonStore | None = None) -> None:
        self.store = store or JsonStore()
        self.data = self.store.load()
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _changed(self) -> None:
        self.store.save(self.data)
        for listener in tuple(self._listeners):
            listener()

    @property
    def active_entry(self) -> TimeEntry | None:
        return next((entry for entry in self.data.entries if entry.running), None)

    def active_projects(self) -> list[Project]:
        return sorted(
            (project for project in self.data.projects if not project.archived),
            key=lambda project: project.name.casefold(),
        )

    def active_tasks(self, project_id: str | None = None) -> list[Task]:
        tasks = (
            task
            for task in self.data.tasks
            if not task.archived
            and (project_id is None or task.project_id == project_id)
        )
        return sorted(tasks, key=lambda task: task.name.casefold())

    def add_project(self, name: str, color: str) -> Project:
        name = name.strip()
        if not name:
            raise TrackerError("Project name is required")
        if any(
            project.name.casefold() == name.casefold() for project in self.data.projects
        ):
            raise TrackerError("A project with this name already exists")
        project = Project(name=name, color=color)
        self.data.projects.append(project)
        self._changed()
        return project

    def update_project(self, project_id: str, name: str, color: str) -> None:
        project = self.project(project_id)
        name = name.strip()
        if not name:
            raise TrackerError("Project name is required")
        if any(
            candidate.id != project_id and candidate.name.casefold() == name.casefold()
            for candidate in self.data.projects
        ):
            raise TrackerError("A project with this name already exists")
        project.name, project.color = name, color
        self._changed()

    def remove_project(self, project_id: str) -> bool:
        project = self.project(project_id)
        referenced = any(entry.project_id == project_id for entry in self.data.entries)
        if referenced:
            project.archived = True
            for task in self.data.tasks:
                if task.project_id == project_id:
                    task.archived = True
        else:
            self.data.projects.remove(project)
            self.data.tasks = [
                task for task in self.data.tasks if task.project_id != project_id
            ]
        self._changed()
        return not referenced

    def add_task(self, name: str, project_id: str) -> Task:
        name = name.strip()
        self.project(project_id)
        if not name:
            raise TrackerError("Task name is required")
        if any(
            task.project_id == project_id and task.name.casefold() == name.casefold()
            for task in self.data.tasks
        ):
            raise TrackerError("This project already has a task with that name")
        task = Task(name=name, project_id=project_id)
        self.data.tasks.append(task)
        self._changed()
        return task

    def update_task(self, task_id: str, name: str, project_id: str) -> None:
        task = self.task(task_id)
        self.project(project_id)
        name = name.strip()
        if not name:
            raise TrackerError("Task name is required")
        if any(
            candidate.id != task_id
            and candidate.project_id == project_id
            and candidate.name.casefold() == name.casefold()
            for candidate in self.data.tasks
        ):
            raise TrackerError("This project already has a task with that name")
        task.name, task.project_id = name, project_id
        self._changed()

    def remove_task(self, task_id: str) -> bool:
        task = self.task(task_id)
        referenced = any(entry.task_id == task_id for entry in self.data.entries)
        if referenced:
            task.archived = True
        else:
            self.data.tasks.remove(task)
        self._changed()
        return not referenced

    def start(self, task_id: str, note: str = "") -> TimeEntry:
        if self.active_entry:
            raise TrackerError("Another timer is already running")
        task = self.task(task_id)
        project = self.project(task.project_id)
        if task.archived or project.archived:
            raise TrackerError("Archived tasks cannot be started")
        entry = TimeEntry(
            task_id=task.id,
            task_name=task.name,
            project_id=project.id,
            project_name=project.name,
            project_color=project.color,
            note=note.strip(),
            start_at=to_iso(utc_now()),
        )
        self.data.entries.append(entry)
        self._changed()
        return entry

    def stop(self, at: datetime | None = None) -> TimeEntry | None:
        entry = self.active_entry
        if entry is None:
            return None
        end = at or utc_now()
        if end <= datetime.fromisoformat(entry.start_at.replace("Z", "+00:00")):
            raise TrackerError("End time must be after start time")
        entry.end_at = to_iso(end)
        self._changed()
        return entry

    def update_entry(
        self,
        entry_id: str,
        task_id: str,
        note: str,
        start_at: datetime,
        end_at: datetime | None,
    ) -> None:
        entry = self.entry(entry_id)
        task = self.task(task_id)
        project = self.project(task.project_id)
        start_at = self._aware(start_at)
        end_at = self._aware(end_at) if end_at else None
        if end_at is not None and end_at <= start_at:
            raise TrackerError("End time must be after start time")
        if end_at is None and self.active_entry not in (None, entry):
            raise TrackerError("Only one timer can run at a time")
        entry.task_id = task.id
        entry.task_name = task.name
        entry.project_id = project.id
        entry.project_name = project.name
        entry.project_color = project.color
        entry.note = note.strip()
        entry.start_at = to_iso(start_at)
        entry.end_at = to_iso(end_at) if end_at else None
        self._changed()

    def delete_entry(self, entry_id: str) -> None:
        self.data.entries.remove(self.entry(entry_id))
        self._changed()

    def entries_between(self, start: date, end: date) -> list[TimeEntry]:
        start_at = datetime.combine(start, time.min).astimezone(timezone.utc)
        end_at = datetime.combine(end, time.max).astimezone(timezone.utc)
        return sorted(
            (
                entry
                for entry in self.data.entries
                if start_at
                <= datetime.fromisoformat(entry.start_at.replace("Z", "+00:00"))
                <= end_at
            ),
            key=lambda entry: entry.start_at,
            reverse=True,
        )

    def report_totals(
        self, start: date, end: date
    ) -> tuple[int, dict[tuple[str, str], int]]:
        totals: dict[tuple[str, str], int] = defaultdict(int)
        for project_totals in self.daily_project_totals(start, end).values():
            for project, seconds in project_totals.items():
                totals[project] += seconds
        total = sum(totals.values())
        return total, dict(totals)

    def daily_project_totals(
        self, start: date, end: date, now: datetime | None = None
    ) -> dict[date, dict[tuple[str, str], int]]:
        """Split entry durations across local days and group them by project."""
        if end < start:
            return {}
        current = now or utc_now()
        totals: dict[date, dict[tuple[str, str], int]] = defaultdict(
            lambda: defaultdict(int)
        )
        for entry in self.data.entries:
            entry_start = datetime.fromisoformat(entry.start_at.replace("Z", "+00:00"))
            entry_end = (
                datetime.fromisoformat(entry.end_at.replace("Z", "+00:00"))
                if entry.end_at
                else current
            )
            first_day = max(start, entry_start.astimezone().date())
            last_day = min(end, entry_end.astimezone().date())
            day = first_day
            while day <= last_day:
                day_start = datetime.combine(day, time.min).astimezone(timezone.utc)
                day_end = datetime.combine(
                    day + timedelta(days=1), time.min
                ).astimezone(timezone.utc)
                overlap_start = max(entry_start, day_start)
                overlap_end = min(entry_end, day_end)
                if overlap_end > overlap_start:
                    project = (entry.project_name, entry.project_color)
                    totals[day][project] += int(
                        (overlap_end - overlap_start).total_seconds()
                    )
                day += timedelta(days=1)
        return {day: dict(projects) for day, projects in totals.items()}

    def total_for_day(self, day: date, now: datetime | None = None) -> int:
        """Return seconds overlapping a local calendar day, including a running timer."""
        day_start = datetime.combine(day, time.min).astimezone(timezone.utc)
        day_end = datetime.combine(day + timedelta(days=1), time.min).astimezone(
            timezone.utc
        )
        current = now or utc_now()
        total = 0
        for entry in self.data.entries:
            entry_start = datetime.fromisoformat(entry.start_at.replace("Z", "+00:00"))
            entry_end = (
                datetime.fromisoformat(entry.end_at.replace("Z", "+00:00"))
                if entry.end_at
                else current
            )
            overlap_start = max(entry_start, day_start)
            overlap_end = min(entry_end, day_end)
            if overlap_end > overlap_start:
                total += int((overlap_end - overlap_start).total_seconds())
        return total

    def project(self, project_id: str) -> Project:
        try:
            return next(item for item in self.data.projects if item.id == project_id)
        except StopIteration as error:
            raise TrackerError("Project no longer exists") from error

    def task(self, task_id: str) -> Task:
        try:
            return next(item for item in self.data.tasks if item.id == task_id)
        except StopIteration as error:
            raise TrackerError("Task no longer exists") from error

    def entry(self, entry_id: str) -> TimeEntry:
        try:
            return next(item for item in self.data.entries if item.id == entry_id)
        except StopIteration as error:
            raise TrackerError("Time entry no longer exists") from error

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.astimezone()
        return value
