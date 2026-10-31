"""End-to-end launch check for the self-contained Claude Desktop bundle."""

import anyio
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from scripts.build_release import build_windows_mcpb_archive


pytestmark = pytest.mark.windows


def test_windows_mcpb_executable_initializes_and_lists_tools(tmp_path):
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
    child_env = os.environ.copy()
    child_env["MUSICBEE_TAGGER_DATA_DIR"] = str(tmp_path / "private-data")
    server = StdioServerParameters(
        command=str(executable),
        args=[],
        env=child_env,
        cwd=tmp_path,
    )

    async def inspect_server():
        with anyio.fail_after(60):
            async with stdio_client(server, errlog=sys.stderr) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await session.list_tools()

    tools_response = anyio.run(inspect_server)
    names = {tool.name for tool in tools_response.tools}
    assert "read_track_metadata" in names
    assert "stage_tag_changes" in names
    assert "get_staged_change" in names
    assert "amend_staged_changes" in names
    assert "withdraw_staged_change" in names
    assert "release_batch" in names

