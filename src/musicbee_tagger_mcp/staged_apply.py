"""CLI-only service for applying staged manifests to audio files."""

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .stage_manifest_store import StageManifestStore
from .staging import get_staging_manager
from .tag_applier import apply_tags_to_file


class StagedChangeApplier:
    """Load and apply manifests; this module is not imported by MCP tools."""

    def __init__(self, staging_dir: Path) -> None:
        self.store = StageManifestStore(staging_dir)

    def load(self, stage_id: str) -> dict:
        return self.store.load(stage_id)

    def apply(self, stage_id: str, create_backup: bool = True) -> dict:
        def apply_locked(manifest: dict) -> dict:
            if manifest.get("applied"):
                return {"status": "already_applied", "stage_id": stage_id}
            if manifest.get("withdrawn"):
                return {"status": "withdrawn", "stage_id": stage_id}
            if manifest.get("failed"):
                return {"status": "failed", "stage_id": stage_id}
            if manifest.get("archived"):
                return {"status": "archived", "stage_id": stage_id}

            result = apply_tags_to_file(
                manifest["absolute_path"],
                manifest["proposed_tags"],
                create_backup=create_backup,
            )
            manifest["applied"] = True
            manifest["applied_at"] = datetime.now(timezone.utc).isoformat()
            backup_path = result.get("backup_created")
            manifest["backup_path"] = backup_path
            return {
                "status": "applied",
                "stage_id": stage_id,
                "display_name": manifest["display_name"],
                "fields_written": result.get("fields_written", []),
                "backup_created": backup_path is not None,
                "backup_path": backup_path,
            }

        _, result = self.store.transact(stage_id, apply_locked)
        return result

    def defer(self, stage_id: str) -> dict:
        """Move a pending stage to the end of the review queue."""
        def update(manifest: dict) -> None:
            if manifest.get("applied") or manifest.get("withdrawn") or manifest.get(
                "failed"
            ) or manifest.get("archived"):
                raise ValueError("Only pending stages can be deferred.")
            now = datetime.now(timezone.utc).isoformat()
            manifest["deferred"] = True
            manifest["deferred_at"] = now
            manifest.setdefault("history", []).append({
                "action": "deferred",
                "at": now,
                "reason": "Moved to the end of the staged review queue.",
            })

        manifest = self.store.mutate(stage_id, update)
        return {"status": "deferred", "stage_id": stage_id,
                "display_name": manifest["display_name"]}

    def mark_failed(self, stage_id: str, reason: str) -> dict:
        """Record a user-declined or failed stage and remove it from pending."""
        def update(manifest: dict) -> None:
            if manifest.get("applied") or manifest.get("withdrawn") or manifest.get(
                "failed"
            ) or manifest.get("archived"):
                raise ValueError("Only pending stages can be marked failed.")
            now = datetime.now(timezone.utc).isoformat()
            manifest["failed"] = True
            manifest["failed_at"] = now
            manifest["failure_reason"] = reason
            manifest.setdefault("history", []).append({
                "action": "failed",
                "at": now,
                "reason": reason,
            })

        manifest = self.store.mutate(stage_id, update)
        return {"status": "failed", "stage_id": stage_id,
                "display_name": manifest["display_name"]}

    def archive_missing_file(self, stage_id: str) -> dict:
        """Archive a pending stage whose source audio file is missing."""
        reason = "Source audio file is missing; it may have been moved or edited."

        def update(manifest: dict) -> None:
            if manifest.get("applied") or manifest.get("withdrawn") or manifest.get(
                "failed"
            ) or manifest.get("archived"):
                raise ValueError("Only pending stages can be archived.")
            now = datetime.now(timezone.utc).isoformat()
            manifest["archived"] = True
            manifest["archived_at"] = now
            manifest["archive_reason"] = reason
            manifest.setdefault("history", []).append({
                "action": "archived",
                "at": now,
                "reason": reason,
            })

        manifest = self.store.mutate(stage_id, update)
        return {"status": "archived", "stage_id": stage_id,
                "display_name": manifest["display_name"], "reason": reason}

    def revert(self, stage_id: str) -> dict:
        """Restore the original audio file from its .bak backup.

        Only works on stages that were applied with a backup. After a
        successful revert the manifest is marked ``reverted`` so it won't
        appear again in the revertable list.
        """
        def update(manifest: dict) -> dict:
            if not manifest.get("applied"):
                raise ValueError("Only applied stages can be reverted.")
            if manifest.get("reverted"):
                return {"status": "already_reverted", "stage_id": stage_id,
                        "display_name": manifest["display_name"]}
            backup_path = manifest.get("backup_path")
            if not backup_path:
                raise ValueError("No backup path stored for this stage; cannot revert.")
            backup = Path(backup_path)
            if not backup.is_file():
                raise FileNotFoundError(
                    f"Backup file not found: {backup_path}. It may have been deleted."
                )
            original_path = Path(manifest["absolute_path"])
            if not original_path.is_file():
                raise FileNotFoundError(
                    f"Original audio file not found: {original_path}."
                )
            # Restore the backup over the current (modified) file
            shutil.copy2(backup, original_path)

            now = datetime.now(timezone.utc).isoformat()
            manifest["reverted"] = True
            manifest["reverted_at"] = now
            manifest.setdefault("history", []).append({
                "action": "reverted",
                "at": now,
                "reason": "User reverted applied staged changes from backup.",
            })
            return {
                "status": "reverted",
                "stage_id": stage_id,
                "display_name": manifest["display_name"],
            }

        _, result = self.store.transact(stage_id, update)
        return result


_applier: Optional[StagedChangeApplier] = None


def get_staged_applier() -> StagedChangeApplier:
    global _applier
    if _applier is None:
        _applier = StagedChangeApplier(get_staging_manager().staging_dir)
    return _applier
