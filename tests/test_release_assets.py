"""Release config files remain aligned with the project package."""

import json
import re
from pathlib import Path


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
