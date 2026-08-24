from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .models import AppData


class StorageError(RuntimeError):
    pass


def default_data_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return root / "local-tracker" / "data.json"


class JsonStore:
    """Atomic JSON persistence with automatic, rotating recovery snapshots."""

    def __init__(
        self,
        path: Path | None = None,
        history_path: Path | None = None,
        history_limit: int = 50,
    ) -> None:
        self.path = path or default_data_path()
        self.backup_path = self.path.with_suffix(".backup.json")
        self.history_path = history_path or self._default_history_path(path)
        self.history_limit = history_limit

    def load(self) -> AppData:
        if not self.path.exists():
            recovered = self._load_recovery()
            if recovered is not None:
                self.save(recovered, preserve_backup=True)
                return recovered
            return AppData()
        try:
            return self._read(self.path)
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as error:
            recovered = self._load_recovery()
            if recovered is not None:
                self.save(recovered, preserve_backup=True)
                return recovered
            raise StorageError(f"Could not read local data: {error}") from error

    def _read(self, path: Path) -> AppData:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("Data file must contain a JSON object")
        return AppData.from_dict(value)

    def save(self, data: AppData, *, preserve_backup: bool = False) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=".data-", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data.to_dict(), handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            if self.path.exists() and not preserve_backup:
                shutil.copy2(self.path, self.backup_path)
            os.replace(temporary_path, self.path)
            self._sync_directory()
            if not preserve_backup:
                self._save_snapshot()
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise StorageError(f"Could not save local data: {error}") from error

    def _load_recovery(self) -> AppData | None:
        candidates = [self.backup_path, *self._snapshots()]
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                return self._read(candidate)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return None

    def _save_snapshot(self) -> None:
        self.history_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        snapshot = self.history_path / f"data-{timestamp}.json"
        temporary = snapshot.with_suffix(".tmp")
        shutil.copy2(self.path, temporary)
        os.replace(temporary, snapshot)
        for old_snapshot in self._snapshots()[self.history_limit :]:
            old_snapshot.unlink(missing_ok=True)

    def _snapshots(self) -> list[Path]:
        if not self.history_path.exists():
            return []
        return sorted(
            self.history_path.glob("data-*.json"),
            key=lambda candidate: candidate.name,
            reverse=True,
        )

    def _default_history_path(self, explicit_path: Path | None) -> Path:
        if explicit_path is None and os.environ.get("FLATPAK_ID"):
            return Path.home() / ".local" / "share" / "local-tracker-backups"
        return self.path.parent / "history"

    def _sync_directory(self) -> None:
        try:
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            # Some filesystems do not support syncing directory descriptors.
            pass
