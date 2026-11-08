"""Shared pytest fixtures and isolation guards for the musicbee-tagger-mcp suite."""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_configure(config):
    """Register custom markers so --strict-markers accepts them."""
    for marker in (
        "network: allows real network access in a test",
        "slow: long-running test",
        "windows: requires Windows platform",
        "requires_audio_fixtures: requires committed audio fixture files",
    ):
        config.addinivalue_line("markers", marker)


@pytest.fixture(autouse=True)
def isolate_app_data(tmp_path, monkeypatch):
    """Redirect all private app-data roots into tmp_path."""
    real_home = Path.home()
    real_appdata = os.environ.get("APPDATA")

    real_home_dir = real_home / "musicbee-tagger-mcp"
    real_appdata_dir = Path(real_appdata) / "musicbee-tagger-mcp" if real_appdata else None
    home_existed = real_home_dir.exists()
    appdata_existed = real_appdata_dir.exists() if real_appdata_dir else False

    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))

    import musicbee_tagger_mcp.data_paths as data_paths
    import musicbee_tagger_mcp.file_registry as file_registry
    import musicbee_tagger_mcp.review_flags as review_flags
    import musicbee_tagger_mcp.staging as staging
    import musicbee_tagger_mcp.staged_apply as staged_apply

    assert data_paths.default_data_dir() == tmp_path

    # Reset cached singletons so they pick up the per-test data root.
    monkeypatch.setattr(file_registry, "_registry", None, raising=False)
    monkeypatch.setattr(review_flags, "_review_store", None, raising=False)
    monkeypatch.setattr(review_flags, "_review_store_directory", None, raising=False)
    monkeypatch.setattr(staging, "_staging_manager", None, raising=False)
    monkeypatch.setattr(staged_apply, "_applier", None, raising=False)

    yield

    if not home_existed:
        assert not real_home_dir.exists(), (
            "test created data under the real home directory"
        )
    if real_appdata_dir and not appdata_existed:
        assert not real_appdata_dir.exists(), (
            "test created data under the real APPDATA directory"
        )


@pytest.fixture(autouse=True)
def block_network(request, monkeypatch):
    """Block socket/urlopen access unless @pytest.mark.network is used."""
    if (request.node.get_closest_marker("network") is not None or
            request.node.get_closest_marker("windows") is not None):
        yield
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

    for module_name in ("musicbee_tagger_mcp.acrcloud", "musicbee_tagger_mcp.tools.text", "musicbee_tagger_mcp.acoustid", "musicbee_tagger_mcp.tools.acoustid"):
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "urllib"):
            request_urllib = getattr(module, "urllib", None)
            if request_urllib is not None and hasattr(request_urllib, "request"):
                monkeypatch.setattr(request_urllib.request, "urlopen", _blocked, raising=False)

    yield


def pytest_collection_modifyitems(config, items):
    """Skip platform/fixture-dependent tests loudly and consistently."""
    ffmpeg_available = shutil.which("ffmpeg") is not None
    audio_fixtures_present = (ROOT / "test_files" / "test_audio_files").exists()

    for item in items:
        if item.get_closest_marker("windows") is not None:
            if sys.platform != "win32" or importlib.util.find_spec("PyInstaller") is None:
                item.add_marker(
                    pytest.mark.skip(reason="Windows and PyInstaller are required")
                )
        if item.get_closest_marker("requires_audio_fixtures") is not None:
            if not (ffmpeg_available and audio_fixtures_present):
                item.add_marker(
                    pytest.mark.skip(
                        reason="ffmpeg and committed audio fixtures are required"
                    )
                )
