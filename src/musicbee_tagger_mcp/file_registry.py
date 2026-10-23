"""File registry: maps opaque UUID tokens to absolute file paths.

Paths are NEVER returned to callers. Only tokens and bare display names
(filename stem, no directory) are exposed outside this module.
"""

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Optional

from .data_paths import ensure_data_subdirectory


class FileRegistry:
    """Token-to-path store with optional persistence for local registration.

    Persistent registries let a human-run local command register files before
    the MCP client starts, without sending paths in MCP tool calls.
    """

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory
        self._store: Dict[str, Path] = {}  # token → absolute path

    def register(self, path: str) -> dict:
        """Register a file path and return a token + display name.

        Returns:
            {"token": str, "display_name": str}
            display_name is the bare filename only — never a path.

        Raises:
            FileNotFoundError: if the path does not exist on disk.
        """
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError("File not found")
        token = str(uuid.uuid4())
        self._store[token] = p
        if self.directory is not None:
            self._save(token, p)
        return {"token": token, "display_name": p.name}

    def register_many(self, paths: list[str]) -> list[dict]:
        """Register a list of paths. Returns list of {token, display_name}."""
        return [self.register(p) for p in paths]

    def resolve(self, token: str) -> Path:
        """Resolve a token to its absolute path (internal use only).

        Raises:
            KeyError: if the token is not registered.
        """
        try:
            normalized_token = str(uuid.UUID(token))
        except (TypeError, ValueError, AttributeError):
            raise KeyError("Unknown file token") from None

        if normalized_token in self._store:
            return self._store[normalized_token]
        if self.directory is None:
            raise KeyError("Unknown file token")

        record_path = self.directory / f"{normalized_token}.json"
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            path = Path(record["path"])
            if record["token"] != normalized_token or not path.is_absolute():
                raise ValueError
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise KeyError("Unknown file token") from None

        self._store[normalized_token] = path
        return path

    def is_registered(self, token: str) -> bool:
        try:
            self.resolve(token)
        except KeyError:
            return False
        return True

    def revoke(self, token: str) -> None:
        """Remove a token from the registry (e.g. after staging is applied)."""
        try:
            normalized_token = str(uuid.UUID(token))
        except (TypeError, ValueError, AttributeError):
            return
        self._store.pop(normalized_token, None)
        if self.directory is not None:
            (self.directory / f"{normalized_token}.json").unlink(missing_ok=True)

    def list_tokens(self) -> list[dict]:
        """Return all registered tokens with their display names (no paths)."""
        entries = {
            token: {"token": token, "display_name": path.name}
            for token, path in self._store.items()
        }
        if self.directory is not None:
            for record_path in self.directory.glob("*.json"):
                try:
                    token = str(uuid.UUID(record_path.stem))
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    path = Path(record["path"])
                    if record["token"] == token and path.is_absolute():
                        entries[token] = {"token": token, "display_name": path.name}
                except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
        return list(entries.values())

    def clear(self) -> int:
        """Delete persisted registrations and return their count."""
        count = len(self.list_tokens())
        self._store.clear()
        if self.directory is not None:
            for record_path in self.directory.glob("*.json"):
                record_path.unlink(missing_ok=True)
        return count

    def _save(self, token: str, path: Path) -> None:
        """Atomically save one token mapping without exposing its path."""
        temporary_path = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.directory,
                delete=False,
                suffix=".tmp",
            ) as temporary:
                json.dump({"token": token, "path": str(path)}, temporary)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self.directory / f"{token}.json")
        except OSError:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._store.pop(token, None)
            raise RuntimeError(
                "Unable to save local registration; check the data directory "
                "and local permissions."
            ) from None


_registry: Optional[FileRegistry] = None


def get_registry() -> FileRegistry:
    """Return the shared persistent registry used by the CLI and MCP server."""
    global _registry
    if _registry is None:
        _registry = FileRegistry(ensure_data_subdirectory("registered"))
    return _registry
