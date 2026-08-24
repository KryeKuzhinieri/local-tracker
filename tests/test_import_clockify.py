from __future__ import annotations

import csv
import json

from local_tracker.import_clockify import import_clockify_csv
from local_tracker.models import AppData, Project
from local_tracker.storage import JsonStore

HEADERS = [
    "Project",
    "Client",
    "Description",
    "Task",
    "User",
    "Group",
    "Email",
    "Tags",
    "Billable",
    "Start Date",
    "Start Time",
    "End Date",
    "End Time",
    "Duration (h)",
    "Duration (decimal)",
    "Billable Rate (USD)",
    "Billable Amount (USD)",
    "Date of creation",
]


def test_clockify_import_merges_projects_and_is_idempotent(tmp_path) -> None:
    csv_path = tmp_path / "clockify.csv"
    rows = [
        {
            "Project": "Convex Solutions",
            "Description": "Review",
            "Email": "private@example.com",
            "Start Date": "23/08/2026",
            "Start Time": "09:00:00",
            "End Date": "23/08/2026",
            "End Time": "10:30:00",
        },
        {
            "Project": "Convex Solutions",
            "Description": "",
            "Email": "private@example.com",
            "Start Date": "24/08/2026",
            "Start Time": "11:00:00",
            "End Date": "24/08/2026",
            "End Time": "11:15:00",
        },
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    store = JsonStore(tmp_path / "data.json", history_path=tmp_path / "backups")
    store.save(AppData(projects=[Project(name="ConvexSolutions")]))

    first = import_clockify_csv(csv_path, store)
    second = import_clockify_csv(csv_path, store)
    data = store.load()

    assert first.imported_entries == 2
    assert first.created_projects == 0
    assert first.created_tasks == 2
    assert second.imported_entries == 0
    assert second.skipped_duplicates == 2
    assert len(data.projects) == 1
    assert {task.name for task in data.tasks} == {"Review", "Untitled task"}
    assert "private@example.com" not in json.dumps(data.to_dict())
