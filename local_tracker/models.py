from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1
DEFAULT_COLOR = "#7c6ff0"


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(slots=True)
class Project:
    name: str
    color: str = DEFAULT_COLOR
    id: str = field(default_factory=new_id)
    archived: bool = False
    created_at: str = field(default_factory=lambda: to_iso(utc_now()))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Project:
        return cls(
            id=str(value["id"]),
            name=str(value["name"]),
            color=str(value.get("color", DEFAULT_COLOR)),
            archived=bool(value.get("archived", False)),
            created_at=str(value.get("created_at", to_iso(utc_now()))),
        )


@dataclass(slots=True)
class Task:
    name: str
    project_id: str
    id: str = field(default_factory=new_id)
    archived: bool = False
    created_at: str = field(default_factory=lambda: to_iso(utc_now()))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Task:
        return cls(
            id=str(value["id"]),
            name=str(value["name"]),
            project_id=str(value["project_id"]),
            archived=bool(value.get("archived", False)),
            created_at=str(value.get("created_at", to_iso(utc_now()))),
        )


@dataclass(slots=True)
class TimeEntry:
    task_id: str
    task_name: str
    project_id: str
    project_name: str
    project_color: str
    start_at: str
    note: str = ""
    end_at: str | None = None
    id: str = field(default_factory=new_id)

    @property
    def running(self) -> bool:
        return self.end_at is None

    def duration_seconds(self, now: datetime | None = None) -> int:
        end = from_iso(self.end_at) if self.end_at else (now or utc_now())
        return max(0, int((end - from_iso(self.start_at)).total_seconds()))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TimeEntry:
        return cls(
            id=str(value["id"]),
            task_id=str(value.get("task_id", "")),
            task_name=str(value.get("task_name", "Untitled task")),
            project_id=str(value.get("project_id", "")),
            project_name=str(value.get("project_name", "No project")),
            project_color=str(value.get("project_color", DEFAULT_COLOR)),
            note=str(value.get("note", "")),
            start_at=str(value["start_at"]),
            end_at=str(value["end_at"]) if value.get("end_at") else None,
        )


@dataclass(slots=True)
class AppData:
    projects: list[Project] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    entries: list[TimeEntry] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "projects": [asdict(project) for project in self.projects],
            "tasks": [asdict(task) for task in self.tasks],
            "entries": [asdict(entry) for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AppData:
        version = int(value.get("schema_version", 1))
        if version > SCHEMA_VERSION:
            raise ValueError(
                f"Data schema {version} is newer than supported schema {SCHEMA_VERSION}"
            )
        return cls(
            schema_version=version,
            projects=[Project.from_dict(item) for item in value.get("projects", [])],
            tasks=[Task.from_dict(item) for item in value.get("tasks", [])],
            entries=[TimeEntry.from_dict(item) for item in value.get("entries", [])],
        )
