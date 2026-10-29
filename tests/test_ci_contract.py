"""Contract tests for CI configuration."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_matrix_versions_are_supported():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*"([^"]+)"', pyproject)
    assert match, "requires-python missing"
    requires = match.group(1)

    workflow = (ROOT / ".github" / "workflows" / "health.yml").read_text(encoding="utf-8")
    matrix_match = re.search(r'python-version:\s*\[([^\]]+)\]', workflow)
    assert matrix_match, "python-version matrix missing"
    versions = [v.strip().strip('"').strip("'") for v in matrix_match.group(1).split(",")]

    # requires-python is ">=3.11, <4.0"; assert every matrix version is >=3.11.
    min_match = re.search(r'>=\s*(\d+)\.(\d+)', requires)
    assert min_match
    min_major, min_minor = int(min_match.group(1)), int(min_match.group(2))
    for version in versions:
        major, minor = (int(x) for x in version.split(".")[:2])
        assert (major, minor) >= (min_major, min_minor), (
            f"CI matrix version {version} is below requires-python {requires}"
        )
