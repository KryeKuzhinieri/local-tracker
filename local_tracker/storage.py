from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .models import AppData


class StorageError(RuntimeError):
    pass


def default_data_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return root / "local-tracker" / "data.json"


class JsonStore:
    """Versioned JSON persistence with atomic writes and one known-good backup."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_data_path()
        self.backup_path = self.path.with_suffix(".backup.json")

    def load(self) -> AppData:
        if not self.path.exists():
            return AppData()
        try:
            return self._read(self.path)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            if self.backup_path.exists():
                try:
                    recovered = self._read(self.backup_path)
                    self.save(recovered, preserve_backup=True)
                    return recovered
                except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                    pass
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
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise StorageError(f"Could not save local data: {error}") from error

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
