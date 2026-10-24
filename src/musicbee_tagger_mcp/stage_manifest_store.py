"""Filesystem persistence for pending tag-change manifests."""

import json
from pathlib import Path
from typing import List, Optional

from .data_paths import ensure_data_subdirectory


def default_staging_dir() -> Path:
    """Return the user's persistent staging directory."""
    return ensure_data_subdirectory("staged")


class StageManifestStore:
    """Read and write manifest JSON while keeping path handling internal."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory or default_staging_dir()

    def save(self, manifest: dict) -> None:
        """Persist one staged-change manifest."""
        path = self.directory / f"{manifest['stage_id']}.json"
        path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def load(self, stage_id: str) -> dict:
        """Load a manifest by its stage identifier."""
        path = self.directory / f"{stage_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No staged change found for stage_id: {stage_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_pending(self) -> List[dict]:
        """Return only path-free summaries of manifests not yet applied."""
        pending = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if not manifest.get("applied", False):
                    pending.append({
                        "stage_id": manifest["stage_id"],
                        "display_name": manifest["display_name"],
                        "created_at": manifest["created_at"],
                        "diff_summary": manifest.get("diff", []),
                        "forensic_score": manifest.get("forensic_score"),
                    })
            except Exception:
                continue
        return pending
