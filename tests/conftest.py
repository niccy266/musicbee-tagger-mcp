"""Shared test fixtures and isolation guards."""

import os
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from musicbee_tagger_mcp.data_paths import default_data_dir


@pytest.fixture(autouse=True)
def isolate_app_data(tmp_path, monkeypatch):
    """Point all app-data roots at the per-test tmp_path and guard the real one."""
    real_root = default_data_dir()
    if real_root.exists():
        before = {path for path in real_root.rglob("*")}
    else:
        before = None

    sandbox = tmp_path / "musicbee-tagger-mcp"
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(sandbox))

    yield

    if before is None:
        assert not real_root.exists(), (
            f"test created application data outside the sandbox: {real_root}"
        )
    else:
        after = {path for path in real_root.rglob("*")} if real_root.exists() else set()
        assert after == before, (
            f"test modified application data outside the sandbox: {real_root}"
        )


@pytest.fixture(autouse=True)
def block_network(request, monkeypatch):
    """Prevent tests from making real network calls unless marked ``network``."""
    if request.node.get_closest_marker("network") is not None:
        return

    real_socket = socket.socket

    class _GuardedSocket(real_socket):
        def __init__(self, *args, **kwargs):
            caller_name = sys._getframe(1).f_code.co_name
            caller_module = sys._getframe(1).f_globals.get("__name__", "")
            if caller_name in {"_fallback_socketpair", "socketpair", "accept"} or caller_module.startswith(
                ("asyncio", "selectors", "anyio", "sniffio", "multiprocessing", "socket")
            ):
                super().__init__(*args, **kwargs)
            else:
                raise RuntimeError("network access in tests")

    def _blocked(*args, **kwargs):
        raise RuntimeError("network access in tests")

    monkeypatch.setattr(socket, "socket", _GuardedSocket)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
