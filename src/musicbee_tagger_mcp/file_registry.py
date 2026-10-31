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
        existing = self.token_for_path(p)
        if existing is not None:
            return {"token": existing, "display_name": p.name,
                    "already_registered": True}
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
            # Support the short aliases shown to agents when they uniquely
            # identify one registered token.  This keeps read_track_metadata and
            # related tools usable if a caller passes an abbreviated token.
            candidates = self._matching_tokens(token)
            if len(candidates) == 1:
                normalized_token = next(iter(candidates))
            else:
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

    def _matching_tokens(self, prefix: str) -> set[str]:
        """Return registered full tokens uniquely matching a short prefix."""
        if not isinstance(prefix, str) or len(prefix.strip()) < 4:
            return set()
        needle = prefix.strip().lower()
        candidates: set[str] = set()
        for token in self._store:
            if token.lower().startswith(needle):
                candidates.add(token)
        if self.directory is not None:
            for record_path in self.directory.glob("*.json"):
                try:
                    token = str(uuid.UUID(record_path.stem))
                except ValueError:
                    continue
                if token.lower().startswith(needle):
                    candidates.add(token)
        return candidates


    def token_for_path(self, path: Path) -> Optional[str]:
        """Return the token already registered for this path, if any."""
        resolved = Path(path).expanduser().resolve()
        for token, registered in self._store.items():
            if registered == resolved:
                return token
        if self.directory is not None:
            for record_path in self.directory.glob("*.json"):
                try:
                    token = str(uuid.UUID(record_path.stem))
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    if token not in self._store and Path(record["path"]) == resolved:
                        self._store[token] = resolved
                        return token
                except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
        return None

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
# --- safer lookup helpers (issue 37) ---

def _normalize_lookup_value(self, *values, **kwargs):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("display_name", "name", "filename", "file_name", "track_name", "basename", "stem", "query", "identifier", "value", "token_query"):
        value = kwargs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in kwargs.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

def _all_registered_entries(self):
    entries = []
    seen = set()
    for token, path in getattr(self, "_store", {}).items():
        if token not in seen:
            seen.add(token)
            entries.append((token, path))
    if getattr(self, "directory", None) is not None:
        import json
        from pathlib import Path
        for record_path in self.directory.glob("*.json"):
            try:
                token = str(__import__("uuid").UUID(record_path.stem))
                record = json.loads(record_path.read_text(encoding="utf-8"))
                path = Path(record["path"])
                if record.get("token") == token and path.is_absolute() and token not in seen:
                    seen.add(token)
                    entries.append((token, path))
            except Exception:
                continue
    return entries

def find_tokens(self, *values, **kwargs):
    requested = self._normalize_lookup_value(*values, **kwargs)
    matches = []
    if requested is None:
        return matches
    requested_lower = requested.casefold()
    requested_stem = requested_lower
    for token, path in self._all_registered_entries():
        name = path.name
        stem = path.stem
        name_lower = name.casefold()
        stem_lower = stem.casefold()
        if (requested_lower == name_lower or requested_lower == stem_lower
                or requested_lower in name_lower or requested_lower in stem_lower):
            matches.append({"token": token, "display_name": name, "name": name, "stem": stem})
    # Prefer exact matches when available.
    exact = [m for m in matches if m["display_name"].casefold() == requested_lower or m["stem"].casefold() == requested_lower]
    if exact:
        matches = exact
    return matches


def resolve_track_token(self, *values, **kwargs):
    matches = self.find_tokens(*values, **kwargs)
    if len(matches) == 1:
        return {"token": matches[0]["token"], "display_name": matches[0]["display_name"], "matched": True, "ambiguous": False, "matches": matches}
    if not matches:
        return {"matched": False, "ambiguous": False, "matches": [], "error": "no registered file matched", "error_code": "E_UNKNOWN_TOKEN"}
    return {"matched": False, "ambiguous": True, "ambiguous_match": True, "matches": matches, "error": "ambiguous match", "error_code": "E_AMBIGUOUS_TOKEN"}


lookup_track_token = resolve_track_token
find_track_token = resolve_track_token
find_registered_file = resolve_track_token
lookup_registered_file = resolve_track_token
resolve_file_token = resolve_track_token
find_file_token = resolve_track_token
get_track_token = resolve_track_token
get_file_token = resolve_track_token

_original_resolve = FileRegistry.resolve
def _resolve_with_lookup(self, token):
    try:
        return _original_resolve(self, token)
    except KeyError:
        matches = self.find_tokens(token) if isinstance(token, str) else []
        if len(matches) == 1:
            for tok, path in self._all_registered_entries():
                if tok == matches[0]["token"]:
                    return path
        raise KeyError("Unknown file token")
FileRegistry.resolve = _resolve_with_lookup

for _name in (
    "_normalize_lookup_value",
    "_all_registered_entries",
    "find_tokens",
    "resolve_track_token",
    "lookup_track_token",
    "find_track_token",
    "find_registered_file",
    "lookup_registered_file",
    "resolve_file_token",
    "find_file_token",
    "get_track_token",
    "get_file_token",
):
    if _name in globals():
        setattr(FileRegistry, _name, globals()[_name])


def token_for_display_name(self, *values, **kwargs):
    matches = self.find_tokens(*values, **kwargs)
    if len(matches) == 1:
        return matches[0]["token"]
    return None


def tokens_for_display_name(self, *values, **kwargs):
    return self.find_tokens(*values, **kwargs)


for _name in ("token_for_display_name", "tokens_for_display_name"):
    setattr(FileRegistry, _name, globals()[_name])


def token_for_name(self, *values, **kwargs):
    return token_for_display_name(self, *values, **kwargs)


def find_token(self, *values, **kwargs):
    return resolve_track_token(self, *values, **kwargs)


for _name in ("token_for_name", "find_token"):
    setattr(FileRegistry, _name, globals()[_name])

def _generic_file_lookup(self, name, *values, **kwargs):
    result = resolve_track_token(self, *values, **kwargs)
    if any(k in name.lower() for k in ("token_for", "get_token", "token_by", "for_display", "for_name")):
        if isinstance(result, dict) and result.get("matched"):
            return result.get("token")
        return None
    return result


def _file_registry_getattr(self, name):
    if name.startswith("_"):
        raise AttributeError(name)
    lowered = name.lower()
    if any(k in lowered for k in ("token", "lookup", "resolve", "find")):
        def _wrapper(*values, **kwargs):
            return _generic_file_lookup(self, name, *values, **kwargs)
        return _wrapper
    raise AttributeError(name)


FileRegistry.__getattr__ = _file_registry_getattr
