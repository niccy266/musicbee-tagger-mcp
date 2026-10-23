"""Build Python distributions and Claude Code release archives."""

from __future__ import annotations

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


def main() -> None:
    """Build source packages and Claude Code release archives."""
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

    bundle = DIST / f"musicbee-tagger-mcp-{version}-windows.zip"
    wheel = next(DIST.glob(f"musicbee_tagger_mcp-{version}-*.whl"))
    source_dist = next(DIST.glob(f"musicbee_tagger_mcp-{version}.tar.gz"))
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(wheel, wheel.name)
        archive.write(source_dist, source_dist.name)
        archive.write(plugin_archive, plugin_archive.name)
        archive.write(marketplace_archive, marketplace_archive.name)
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
    print(f"Windows bundle: {bundle.name}")


if __name__ == "__main__":
    main()
