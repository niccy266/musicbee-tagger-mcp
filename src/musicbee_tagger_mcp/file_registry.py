"""File registry: maps opaque UUID tokens to absolute file paths.

Paths are NEVER returned to callers. Only tokens and bare display names
(filename stem, no directory) are exposed outside this module.
"""

import uuid
from pathlib import Path
from typing import Dict, Optional


class FileRegistry:
    """Session-scoped, in-memory token → absolute path store.

    The registry is the only place that knows the real paths.
    All MCP tools receive tokens; the registry resolves them internally.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Path] = {}  # token → absolute path

    def register(self, path: str) -> dict:
        """Register a file path and return a token + display name.

        Returns:
            {"token": str, "display_name": str}
            display_name is the bare filename only — never a path.

        Raises:
            FileNotFoundError: if the path does not exist on disk.
        """
        p = Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        token = str(uuid.uuid4())
        self._store[token] = p
        return {"token": token, "display_name": p.name}

    def register_many(self, paths: list[str]) -> list[dict]:
        """Register a list of paths. Returns list of {token, display_name}."""
        return [self.register(p) for p in paths]

    def resolve(self, token: str) -> Path:
        """Resolve a token to its absolute path (internal use only).

        Raises:
            KeyError: if the token is not registered.
        """
        if token not in self._store:
            raise KeyError(f"Unknown token: {token!r}. Was the file registered?")
        return self._store[token]

    def is_registered(self, token: str) -> bool:
        return token in self._store

    def revoke(self, token: str) -> None:
        """Remove a token from the registry (e.g. after staging is applied)."""
        self._store.pop(token, None)

    def list_tokens(self) -> list[dict]:
        """Return all registered tokens with their display names (no paths)."""
        return [
            {"token": t, "display_name": p.name}
            for t, p in self._store.items()
        ]


# Module-level singleton for the MCP server process lifetime
_registry = FileRegistry()


def get_registry() -> FileRegistry:
    return _registry
