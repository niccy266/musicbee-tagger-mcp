"""End-to-end launch check for the self-contained Claude Desktop bundle."""

import json
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.build_release import build_windows_mcpb_archive


pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or importlib.util.find_spec("PyInstaller") is None,
    reason="The Windows MCPB smoke test requires Windows and PyInstaller",
)


def test_windows_mcpb_executable_initializes_and_lists_tools(tmp_path, monkeypatch):
    """Build the Windows extension and verify the bundled server speaks MCP."""
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "release" / "mcpb" / "manifest.json").read_text(encoding="utf-8")
    )
    bundle = tmp_path / "musicbee-tagger-windows.mcpb"
    build_windows_mcpb_archive(bundle, manifest["version"])

    with zipfile.ZipFile(bundle) as archive:
        archive.extract("server/musicbee-tagger-mcp.exe", tmp_path)

    executable = tmp_path / "server" / "musicbee-tagger-mcp.exe"
    monkeypatch.setenv("MUSICBEE_TAGGER_DATA_DIR", str(tmp_path / "private-data"))
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "package-smoke-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    process = subprocess.run(
        [str(executable)],
        input="\n".join(json.dumps(message) for message in messages) + "\n",
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    responses = [json.loads(line) for line in process.stdout.splitlines() if line]
    tools_response = next(response for response in responses if response.get("id") == 2)
    names = {tool["name"] for tool in tools_response["result"]["tools"]}
    assert "read_track_metadata" in names
    assert "stage_tag_changes" in names
    assert len(names) == 16
