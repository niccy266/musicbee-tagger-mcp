"""Build Python distributions and desktop-client release archives."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def project_version() -> str:
    """Read the package version from the project metadata."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    if not match:
        raise ValueError("Could not read project version from pyproject.toml")
    return match.group(1)


def add_tree(archive: zipfile.ZipFile, source: Path, archive_root: str) -> None:
    """Add every file below a source directory to an archive."""
    for path in sorted(source.rglob("*")):
        if path.is_file():
            relative = path.relative_to(source).as_posix()
            archive.write(path, f"{archive_root}/{relative}")


def build_mcpb_archive(output_path: Path, version: str) -> None:
    """Build a Claude Desktop MCP Bundle with the Python project sources."""
    manifest_path = ROOT / "release" / "mcpb" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        raise ValueError("MCPB manifest version must match pyproject.toml")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(manifest_path, "manifest.json")
        archive.write(ROOT / "release" / "mcpb" / "server.py", "server.py")
        archive.write(ROOT / "pyproject.toml", "pyproject.toml")
        package_source = ROOT / "src" / "musicbee_tagger_mcp"
        for path in sorted(package_source.rglob("*.py")):
            archive.write(path, path.relative_to(ROOT).as_posix())


def main() -> None:
    """Build source packages and Claude client release archives."""
    version = project_version()
    DIST.mkdir(exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(DIST)],
        cwd=ROOT,
        check=True,
    )

    plugin_source = (
        ROOT / "release" / "claude-marketplace" / "plugins" / "musicbee-tagger"
    )
    plugin_archive = DIST / f"musicbee-tagger-claude-plugin-{version}.zip"
    with zipfile.ZipFile(plugin_archive, "w", zipfile.ZIP_DEFLATED) as archive:
        add_tree(archive, plugin_source, "musicbee-tagger")

    marketplace_archive = DIST / f"musicbee-tagger-claude-marketplace-{version}.zip"
    with zipfile.ZipFile(marketplace_archive, "w", zipfile.ZIP_DEFLATED) as archive:
        add_tree(archive, ROOT / "release" / "claude-marketplace", "claude-marketplace")

    mcpb_archive = DIST / f"musicbee-tagger-mcp-{version}.mcpb"
    build_mcpb_archive(mcpb_archive, version)

    bundle = DIST / f"musicbee-tagger-mcp-{version}-windows.zip"
    wheel = next(DIST.glob(f"musicbee_tagger_mcp-{version}-*.whl"))
    source_dist = next(DIST.glob(f"musicbee_tagger_mcp-{version}.tar.gz"))
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(wheel, wheel.name)
        archive.write(source_dist, source_dist.name)
        archive.write(plugin_archive, plugin_archive.name)
        archive.write(marketplace_archive, marketplace_archive.name)
        archive.write(mcpb_archive, mcpb_archive.name)
        add_tree(
            archive,
            ROOT / "release" / "claude-marketplace",
            "claude-marketplace",
        )
        archive.write(
            ROOT / "release" / "windows" / "install.ps1",
            "install.ps1",
        )
        archive.write(
            ROOT / "release" / "claude-code" / "mcp-config.json",
            "mcp-config.json",
        )
        archive.write(ROOT / "README.md", "README.md")

    print(f"Built release {version} in {DIST}")
    print(f"Plugin archive: {plugin_archive.name}")
    print(f"Marketplace archive: {marketplace_archive.name}")
    print(f"Claude Desktop MCP Bundle: {mcpb_archive.name}")
    print(f"Windows bundle: {bundle.name}")


if __name__ == "__main__":
    main()
