"""Release config files remain aligned with the project package."""

import json
import re
import zipfile
from pathlib import Path

from scripts.build_release import build_mcpb_archive


ROOT = Path(__file__).resolve().parents[1]


def test_release_configs_use_supported_claude_shapes():
    """Validate the Claude Code user config and plugin marketplace structure."""
    standalone = json.loads(
        (ROOT / "release" / "claude-code" / "mcp-config.json").read_text(
            encoding="utf-8"
        )
    )
    server = standalone["mcpServers"]["musicbee-tagger"]
    assert server["type"] == "stdio"
    assert server["command"] == "cmd.exe"
    assert server["args"][-1] == "K:\\bin\\musicbee-tagger-mcp.cmd"
    assert server["env"]["MUSICBEE_TAGGER_DATA_DIR"].endswith("\\data")

    marketplace = json.loads(
        (ROOT / "release" / "claude-marketplace" / ".claude-plugin" /
         "marketplace.json").read_text(encoding="utf-8")
    )
    plugin_path = (
        ROOT / "release" / "claude-marketplace" / "plugins" / "musicbee-tagger"
    )
    plugin = json.loads(
        (plugin_path / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    plugin_server = json.loads(
        (plugin_path / ".mcp.json").read_text(encoding="utf-8")
    )["musicbee-tagger"]

    assert marketplace["plugins"][0]["source"] == "./plugins/musicbee-tagger"
    assert plugin["mcpServers"] == "./.mcp.json"
    assert plugin_server["command"] == "cmd.exe"
    assert plugin_server["args"][-1] == server["args"][-1]
    assert plugin_server["env"] == server["env"]


def test_plugin_version_matches_project_version():
    """Keep the plugin release version synchronized with the package version."""
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', project).group(1)
    plugin = json.loads(
        (
            ROOT
            / "release"
            / "claude-marketplace"
            / "plugins"
            / "musicbee-tagger"
            / ".claude-plugin"
            / "plugin.json"
        ).read_text(encoding="utf-8")
    )

    assert plugin["version"] == project_version


def test_all_release_version_markers_match_project_version():
    """Keep the package, protocol user agent, docs, plugin, and MCPB aligned."""
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', project).group(1)
    package = (ROOT / "src" / "musicbee_tagger_mcp" / "__init__.py").read_text(
        encoding="utf-8"
    )
    musicbrainz_api = (
        ROOT / "src" / "musicbee_tagger_mcp" / "musicbrainz_api.py"
    ).read_text(encoding="utf-8")
    plugin = json.loads(
        (
            ROOT
            / "release"
            / "claude-marketplace"
            / "plugins"
            / "musicbee-tagger"
            / ".claude-plugin"
            / "plugin.json"
        ).read_text(encoding="utf-8")
    )
    mcpb = json.loads(
        (ROOT / "release" / "mcpb" / "manifest.json").read_text(encoding="utf-8")
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert f'__version__ = "{project_version}"' in package
    assert f'    "{project_version}",' in musicbrainz_api
    assert plugin["version"] == project_version
    assert mcpb["version"] == project_version
    assert "mcp>=2.0.0" in project
    assert f"musicbee_tagger_mcp-{project_version}-py3-none-any.whl" in readme
    assert f"musicbee-tagger-mcp-{project_version}.mcpb" in readme
    assert f"musicbee_tagger_mcp-{project_version}-py3-none-any.whl" in guide
    assert f"musicbee-tagger-mcp-{project_version}.mcpb" in guide


def test_plugin_bundles_the_investigator_skill():
    """Keep Claude's plugin skill discoverable and synchronized with its source."""
    source_skill = (
        ROOT / ".agents" / "skills" / "musicbee-investigator" / "SKILL.md"
    ).read_text(encoding="utf-8")
    plugin_skill = (
        ROOT
        / "release"
        / "claude-marketplace"
        / "plugins"
        / "musicbee-tagger"
        / "skills"
        / "musicbee-investigator"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert plugin_skill == source_skill
    assert "name: musicbee-investigator" in plugin_skill
    assert "description:" in plugin_skill


def test_repository_marketplace_tracks_plugin_in_release_tree():
    """Expose the release plugin through a repository-hosted marketplace."""
    marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )

    assert marketplace["name"] == "musicbee-tagger"
    assert marketplace["plugins"][0]["name"] == "musicbee-tagger"
    assert (
        marketplace["plugins"][0]["source"]
        == "./release/claude-marketplace/plugins/musicbee-tagger"
    )


def test_human_playlist_registration_command_is_packaged():
    """Ensure the private registration CLI is installed alongside the server."""
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    installer = (ROOT / "release" / "windows" / "install.ps1").read_text(
        encoding="utf-8"
    )

    assert (
        'musicbee-tagger-register-playlist = '
        '"musicbee_tagger_mcp.register_playlist_cli:main"'
    ) in project
    assert (
        'musicbee-tagger-clear-registrations = '
        '"musicbee_tagger_mcp.clear_registrations_cli:main"'
    ) in project
    assert "musicbee-tagger-register-playlist.exe" in installer
    assert "musicbee-tagger-register-playlist.cmd" in installer
    assert '"$registerPlaylistExe" %*' in installer
    assert "pip install --force-reinstall --no-deps $resolvedWheel" in installer
    assert "musicbee-tagger-clear-registrations.exe" in installer
    assert "musicbee-tagger-clear-registrations.cmd" in installer
    assert "Get-CimInstance Win32_Process" in installer
    assert "Close MCP clients using this server" in installer


def test_source_checkout_installer_builds_and_installs_local_wheel():
    """Allow installing directly from the repository without extracting a release."""
    installer = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "pip wheel --no-deps" in installer
    assert "$repositoryRoot" in installer
    assert "release\\windows\\install.ps1" in installer
    assert "-WheelPath $wheels[0].FullName" in installer
    assert "-InstallRoot $InstallRoot" in installer
    assert "-BinRoot $BinRoot" in installer
    assert "musicbee-tagger-wheel-" in installer


def test_mcpb_manifest_matches_project_and_uses_supported_uv_runtime():
    """Keep the Claude Desktop extension manifest aligned with the package."""
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', project).group(1)
    manifest = json.loads(
        (ROOT / "release" / "mcpb" / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["manifest_version"] == "0.4"
    assert manifest["name"] == "musicbee-tagger-mcp"
    assert manifest["version"] == project_version
    assert manifest["server"]["type"] == "uv"
    assert manifest["server"]["entry_point"] == "server.py"
    assert manifest["server"]["mcp_config"]["command"] == "uv"
    assert manifest["server"]["mcp_config"]["args"] == [
        "run",
        "--directory",
        "${__dirname}",
        "server.py",
    ]
    assert manifest["server"]["mcp_config"]["env"] == {
        "MUSICBEE_TAGGER_DATA_DIR": "${user_config.data_directory}"
    }
    assert manifest["user_config"]["data_directory"]["type"] == "directory"
    assert manifest["user_config"]["data_directory"]["default"] == (
        "K:\\tools\\mcp-servers\\musicbee-tags\\data"
    )
    assert manifest["compatibility"]["platforms"] == ["darwin", "linux", "win32"]
    assert manifest["compatibility"]["runtimes"]["python"] == ">=3.11,<3.12"
    assert {tool["name"] for tool in manifest["tools"]} == {
        "read_track_metadata",
        "extract_filename_clues",
        "get_batch_brief",
        "search_canonical_release",
        "verify_mbid",
        "preview_tags",
        "stage_tag_changes",
        "list_staged_changes",
        "next_batch",
        "complete_batch",
        "job_status",
        "list_jobs",
        "enqueue_batch_operation",
        "list_batch_operations",
        "update_batch_operation",
        "repair_mojibake",
    }


def test_mcpb_archive_contains_only_runtime_project_files(tmp_path):
    """Build an installable MCPB without repository or test artifacts."""
    manifest = json.loads(
        (ROOT / "release" / "mcpb" / "manifest.json").read_text(encoding="utf-8")
    )
    output = tmp_path / "musicbee-tagger.mcpb"

    build_mcpb_archive(output, manifest["version"])

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert archive.testzip() is None
        assert "manifest.json" in names
        assert "pyproject.toml" in names
        assert ".python-version" in names
        assert "README.md" in names
        assert "server.py" in names
        assert "src/musicbee_tagger_mcp/server.py" in names
        assert any(name.startswith("src/musicbee_tagger_mcp/tools/") for name in names)
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        assert not any(name.startswith(("tests/", ".git/")) for name in names)
        assert archive.read(".python-version").decode("utf-8").strip() == "3.11"
        bundled_pyproject = archive.read("pyproject.toml").decode("utf-8")
        assert "[tool.uv]" not in bundled_pyproject
