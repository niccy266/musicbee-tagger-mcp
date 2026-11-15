"""Staging manager: writes proposed tag changes to a local manifest directory.

The agent calls stage_tag_changes() and receives back a stage_id (UUID).
It never sees the manifest path, the absolute file path, or the staging dir.

The USER applies staged changes via the CLI:
    python -m musicbee_tagger_mcp.apply_staged --stage-id <uuid>
    python -m musicbee_tagger_mcp.apply_staged --all --dry-run
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .artist_credit import normalize_artist_value
from .field_map import FIELD_MAP
from .match_store import resolve_match_for_recording, resolve_match_for_token
from .metadata_reader import read_audio_metadata
from .stage_manifest_store import StageManifestStore
from .tag_writer import preview_tag_changes

_LOCAL_PATH = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\\/][^\s]*|\\\\[^\s\\]+\\[^\s]*"
    r"|(?<![:/])/(?:[^/\s]+/)*[^/\s]+)"
)


def _changed_fields(file_path: str, proposed_tags: Dict[str, Any]) -> list[dict]:
    """Recompute the changed fields without returning or persisting the path."""
    try:
        preview_diff = preview_tag_changes(file_path, proposed_tags).get("diff", {})
    except Exception:
        raise ValueError(
            "Unable to re-check the audio file; no stage was changed."
        ) from None
    if isinstance(preview_diff, dict):
        return [
            {"field": field, "old": change.get("before"), "new": change.get("after")}
            for field, change in preview_diff.items()
            if change.get("changed")
        ]
    if isinstance(preview_diff, list):
        return preview_diff
    raise ValueError("Tag preview returned an invalid diff.")


def _validate_reason(reason: str) -> str:
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must explain the requested stage change.")
    if len(reason) > 1000:
        raise ValueError("reason must be at most 1000 characters.")
    without_urls = re.sub(r"https?://\S+", "", reason)
    if _LOCAL_PATH.search(without_urls):
        raise ValueError("reason must not contain local filesystem paths.")
    return reason.strip()


def _path_free(value: Any) -> Any:
    """Redact accidental local paths in metadata returned to agents."""
    if isinstance(value, dict):
        return {key: _path_free(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_path_free(item) for item in value]
    if isinstance(value, str):
        parts = re.split(r"(https?://\S+)", value)
        return "".join(
            part if part.startswith(("http://", "https://"))
            else _LOCAL_PATH.sub("(local path omitted)", part)
            for part in parts
        )
    return value

class AuditReport(list):
    """Audit report that is primarily a list of flagged stages.

    Mapping-style access is delegated to the full report dictionary, so callers
    that expect either a list or a dict can use the same object.
    """

    def __init__(self, flagged, report):
        super().__init__(flagged)
        self._report = dict(report)

    def _mapping(self):
        return self._report

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._report[key]
        return super().__getitem__(key)

    def __contains__(self, key):
        if isinstance(key, str):
            return key in self._report
        return super().__contains__(key)

    def get(self, key, default=None):
        if isinstance(key, str):
            return self._report.get(key, default)
        return default

    def keys(self):
        return self._report.keys()

    def values(self):
        return self._report.values()

    def items(self):
        return self._report.items()

    def __repr__(self):
        return repr(self._report)



class StagingManager:
    """Manages pending tag-change manifests on disk."""

    def __init__(self, staging_dir: Optional[Path] = None) -> None:
        self.store = StageManifestStore(staging_dir)
        self.staging_dir = self.store.directory

    def stage(
        self,
        absolute_path: Path,
        display_name: str,
        proposed_tags: Dict[str, Any],
        mb_recording_id: Optional[str] = None,
        mb_release_id: Optional[str] = None,
        forensic_score: Optional[float] = None,
        match_source: Optional[str] = None,
        match_confidence: Optional[float] = None,
        notes: str = "",
        manual_override: bool = False,
        manual_override_justification: Optional[str] = None,
        override_justification: Optional[str] = None,
        override_reason: Optional[str] = None,
        justification: Optional[str] = None,
        token: Optional[str] = None,
        job_id: Optional[str] = None,
        batch: Optional[str] = None,
        note: Optional[str] = None,
        rationale: Optional[str] = None,
        **kwargs: Any,
    ) -> dict:
        """Write a pending change manifest and return a stage_id + summary.

        The absolute_path is stored inside the manifest file on disk.
        It is NEVER returned to the caller.

        Returns:
            {"stage_id": str, "display_name": str, "diff_summary": list, "notes": str}
        """
        # Normalize artist tag using stored MusicBrainz credit names (no network calls).
        proposed_tags = dict(proposed_tags)
        artist_warnings: List[str] = []
        artist_norm_note: Optional[str] = None
        if isinstance(proposed_tags.get("artist"), str):
            raw_artist = proposed_tags["artist"]
            credited_names = self._lookup_artist_names(
                token=token,
                mb_recording_id=mb_recording_id or proposed_tags.get("musicbrainz_track_id"),
            )
            normalized_artist, artist_warnings = normalize_artist_value(
                raw_artist, credited_names
            )
            if normalized_artist != raw_artist:
                proposed_tags["artist"] = normalized_artist
                artist_norm_note = (
                    f"artist normalised to semicolon-separated: '{raw_artist}' -> '{normalized_artist}'"
                )

        # Generate the field-by-field diff (reads file for current values).
        diff = _changed_fields(str(absolute_path), proposed_tags)
        try:
            baseline_tags = read_audio_metadata(str(absolute_path)).get("tags", {})
        except Exception:
            baseline_tags = None

        if not manual_override:
            manual_override = kwargs.get("manual_override", False)
        override_text = (
            manual_override_justification
            or override_justification
            or override_reason
            or justification
            or kwargs.get("manual_override_justification")
            or kwargs.get("override_justification")
            or kwargs.get("override_reason")
            or kwargs.get("justification")
        )
        is_manual_override = bool(manual_override or override_text)
        if is_manual_override:
            if not isinstance(override_text, str) or not override_text.strip():
                raise ValueError("justification is required for a manual override")
            override_text = override_text.strip()
        else:
            override_text = None

        if not notes and note:
            notes = note
        if rationale:
            notes = (str(notes).strip() + ", " + str(rationale).strip()).strip() if notes else str(rationale).strip()
        notes = notes if isinstance(notes, str) else ("" if notes is None else str(notes))
        if artist_norm_note:
            notes = f"{notes.strip()} | {artist_norm_note}".strip(" |") if notes.strip() else artist_norm_note

        stage_id = str(uuid.uuid4())
        manifest = {
            "stage_id": stage_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "previous_tags": baseline_tags,
            "display_name": display_name,
            "absolute_path": str(absolute_path),  # stored on disk, never returned
            "token": token,
            "job_id": job_id,
            "batch": batch,
            "proposed_tags": proposed_tags,
            "diff": diff,
            "mb_recording_id": mb_recording_id,
            "mb_release_id": mb_release_id,
            "forensic_score": forensic_score,
            "match_source": match_source,
            "match_confidence": match_confidence,
            "notes": notes,
            "note": notes,
            "rationale": notes,
            "manual_override": is_manual_override,
            "manual_override_justification": override_text,
            "override_justification": override_text,
            "applied": False,
            "withdrawn": False,
            "revision": 1,
            "history": [],
        }

        if is_manual_override:
            manifest.setdefault("history", []).append({
                "action": "manual_override",
                "at": manifest["created_at"],
                "reason": override_text,
            })

        self.store.save(manifest)

        # Return only safe, non-path fields to the caller
        response = {
            "stage_id": stage_id,
            "display_name": display_name,
            "revision": 1,
            "diff_summary": diff,
            "notes": notes,
            "message": (
                f"Staged {len(diff)} field change(s) for '{display_name}'. "
                f"Run `python -m musicbee_tagger_mcp.apply_staged --stage-id {stage_id}` to apply."
            ),
        }
        if artist_warnings:
            response["warnings"] = artist_warnings
        return response

    def stage_manual_override(self, *args, **kwargs):
        kwargs.setdefault("manual_override", True)
        return self.stage(*args, **kwargs)

    def list_pending(self) -> List[dict]:
        """List all pending (not yet applied) staged changes — safe fields only."""
        return self.store.list_pending()
    def list_staged_changes(self, *args, **kwargs):

        return self.store.list_staged_changes(*args, **kwargs)

    def annotate(self, *args, **kwargs):

        return annotate_staged_change(self, *args, **kwargs)


    def get(self, stage_id: str) -> dict:
        """Return review context and current tags without revealing the path or token."""
        manifest = self.store.load(stage_id)
        try:
            current_tags = read_audio_metadata(manifest["absolute_path"]).get("tags", {})
            current_tags_error = None
        except Exception:
            current_tags = None
            current_tags_error = "Unable to read the audio file's current tags."
        return _path_free({
            "stage_id": manifest["stage_id"],
            "display_name": manifest["display_name"],
            "created_at": manifest["created_at"],
            "status": self._status(manifest),
            "revision": manifest.get("revision", 1),
            "notes": manifest.get("notes", ""),
            "proposed_tags": manifest.get("proposed_tags", {}),
            "diff_summary": manifest.get("diff", []),
            "mb_recording_id": manifest.get("mb_recording_id"),
            "mb_release_id": manifest.get("mb_release_id"),
            "forensic_score": manifest.get("forensic_score"),
            "match_source": manifest.get("match_source"),
            "match_confidence": manifest.get("match_confidence"),
            "manual_override": manifest.get("manual_override", False),
            "manual_override_justification": manifest.get("manual_override_justification"),
            "override_justification": manifest.get("override_justification"),
            "current_tags": current_tags,
            "current_tags_error": current_tags_error,
            "history": manifest.get("history", []),
        })

    def amend(
        self,
        stage_id: str,
        expected_revision: int,
        new_tags: Dict[str, Any],
        reason: str,
        remove_fields: Optional[List[str]] = None,
        mb_recording_id: Optional[str] = None,
        mb_release_id: Optional[str] = None,
        match_source: Optional[str] = None,
        match_confidence: Optional[float] = None,

        notes: Optional[str] = None,
        note: Optional[str] = None,
        rationale: Optional[str] = None,
    ) -> dict:
        """Revise a pending proposal and recompute its diff; never writes audio."""
        reason = _validate_reason(reason)
        if not notes and note:
            notes = note
        if rationale:
            notes = (str(notes).strip() + ", " + str(rationale).strip()).strip() if notes else str(rationale).strip()
        if notes is not None:
            notes = notes if isinstance(notes, str) else ("" if notes is None else str(notes))
            stripped_notes = notes.strip()
            if stripped_notes:
                if len(stripped_notes) > 2000:
                    raise ValueError("note must be at most 2000 characters.")
                without_urls = __import__("re").sub(r"https?://\\S+", "", stripped_notes)
                if _LOCAL_PATH.search(without_urls):
                    raise ValueError("note must not contain local filesystem paths.")
            else:
                notes = None

        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1
        ):
            raise ValueError("expected_revision must be a positive integer.")
        if not isinstance(new_tags, dict):
            raise ValueError("new_tags must be an object of canonical tag fields.")
        if any(not isinstance(field, str) for field in new_tags):
            raise ValueError("new_tags keys must be canonical tag field names.")
        invalid_fields = sorted(set(new_tags) - set(FIELD_MAP))
        if invalid_fields:
            raise ValueError("Unsupported tag field(s): " + ", ".join(invalid_fields))
        if remove_fields is None:
            remove_fields = []
        if not isinstance(remove_fields, list) or any(
            not isinstance(field, str) for field in remove_fields
        ):
            raise ValueError("remove_fields must be a list of canonical tag field names.")
        if len(set(remove_fields)) != len(remove_fields):
            raise ValueError("remove_fields must not contain duplicates.")
        invalid_removals = sorted(set(remove_fields) - set(FIELD_MAP))
        if invalid_removals:
            raise ValueError(
                "Unsupported tag field(s): " + ", ".join(invalid_removals)
            )
        if set(new_tags) & set(remove_fields):
            raise ValueError("A field cannot be updated and removed in the same amendment.")
        for field, value in new_tags.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (str, int, float))
                or not str(value).strip()
            ):
                raise ValueError(
                    f"{field} must be a non-empty text or numeric value; "
                    "use remove_fields to drop a field from the proposal."
                )
            if isinstance(value, str) and _LOCAL_PATH.search(
                re.sub(r"https?://\S+", "", value)
            ):
                raise ValueError(f"{field} must not contain a local filesystem path.")
            if field in {
                "musicbrainz_track_id",
                "musicbrainz_release_id",
                "musicbrainz_artist_id",
            }:
                self._validate_mbid(field, str(value))
        for field, value in (
            ("mb_recording_id", mb_recording_id),
            ("mb_release_id", mb_release_id),
        ):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} must be text or omitted.")
            if value and len(value) > 100:
                raise ValueError(f"{field} must be at most 100 characters.")
            if value and _LOCAL_PATH.search(value):
                raise ValueError(f"{field} must not contain a local filesystem path.")
            if value and value.strip():
                self._validate_mbid(field, value)
        if (
            not new_tags
            and not remove_fields
            and mb_recording_id is None
            and mb_release_id is None
            and notes is None
            and note is None
            and rationale is None
        ):
            raise ValueError("Provide tag fields, fields to remove, or a MusicBrainz ID to amend.")

        amend_warnings: List[str] = []

        def update(manifest: dict) -> None:
            self._require_pending(manifest)
            current_revision = manifest.get("revision", 1)
            if expected_revision != current_revision:
                raise ValueError(
                    "Stage revision changed; read the stage again. "
                    f"Current revision is {current_revision}."
                )
            proposed = dict(manifest.get("proposed_tags", {}))
            missing_removals = sorted(set(remove_fields) - set(proposed))
            if missing_removals:
                raise ValueError(
                    "Field(s) are not in the staged proposal: "
                    + ", ".join(missing_removals)
                )
            proposed.update(new_tags)
            for field in remove_fields:
                proposed.pop(field)

            amend_norm_note: Optional[str] = None
            if isinstance(new_tags.get("artist"), str) and isinstance(proposed.get("artist"), str):
                raw_artist = proposed["artist"]
                effective_rec_id = (
                    (mb_recording_id.strip() or None)
                    if mb_recording_id is not None
                    else manifest.get("mb_recording_id")
                ) or proposed.get("musicbrainz_track_id")
                credited_names = self._lookup_artist_names(
                    token=manifest.get("token"),
                    mb_recording_id=effective_rec_id,
                )
                normalized_artist, warnings = normalize_artist_value(
                    raw_artist, credited_names
                )
                amend_warnings.extend(warnings)
                if normalized_artist != raw_artist:
                    proposed["artist"] = normalized_artist
                    amend_norm_note = (
                        f"artist normalised to semicolon-separated: '{raw_artist}' -> '{normalized_artist}'"
                    )

            diff = _changed_fields(manifest["absolute_path"], proposed)
            if not diff:
                raise ValueError(
                    "Amendment leaves no tag changes to apply; withdraw the stage instead."
                )

            now = datetime.now(timezone.utc).isoformat()
            amended_fields = list(new_tags) + [f"removed:{field}" for field in remove_fields]
            if mb_recording_id is not None:
                manifest["mb_recording_id"] = mb_recording_id.strip() or None
                amended_fields.append("mb_recording_id")
            if mb_release_id is not None:
                manifest["mb_release_id"] = mb_release_id.strip() or None
                amended_fields.append("mb_release_id")
            if match_source is not None:
                manifest["match_source"] = match_source.strip() if isinstance(match_source, str) else match_source
                amended_fields.append("match_source")

            if match_confidence is not None:
                manifest["match_confidence"] = match_confidence
                amended_fields.append("match_confidence")
            effective_notes = notes if notes else manifest.get("notes", "")
            if amend_norm_note:
                effective_notes = (
                    f"{effective_notes.strip()} | {amend_norm_note}".strip(" |")
                    if isinstance(effective_notes, str) and effective_notes.strip()
                    else amend_norm_note
                )
            if notes or amend_norm_note:
                manifest["notes"] = effective_notes
                manifest["note"] = effective_notes
                manifest["rationale"] = effective_notes
                if notes:
                    amended_fields.append("notes")

            manifest["proposed_tags"] = proposed
            manifest["diff"] = diff
            manifest["revision"] = current_revision + 1
            manifest["updated_at"] = now
            manifest.setdefault("history", []).append({
                "action": "amended",
                "revision": manifest["revision"],
                "at": now,
                "fields": amended_fields,
                "reason": reason,
            })

        manifest = self.store.mutate(stage_id, update)
        result = {
            "stage_id": manifest["stage_id"],
            "display_name": manifest["display_name"],
            "status": self._status(manifest),
            "revision": manifest["revision"],
            "diff_summary": manifest["diff"],
        }
        if amend_warnings:
            result["warnings"] = amend_warnings
        return _path_free(result)

    def withdraw(self, stage_id: str, expected_revision: int, reason: str) -> dict:
        """Soft-withdraw a pending proposal so it cannot be applied."""
        reason = _validate_reason(reason)
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1
        ):
            raise ValueError("expected_revision must be a positive integer.")

        def update(manifest: dict) -> None:
            self._require_pending(manifest)
            current_revision = manifest.get("revision", 1)
            if expected_revision != current_revision:
                raise ValueError(
                    "Stage revision changed; read the stage again. "
                    f"Current revision is {current_revision}."
                )
            now = datetime.now(timezone.utc).isoformat()
            manifest["withdrawn"] = True
            manifest["withdrawn_at"] = now
            manifest["withdrawal_reason"] = reason
            manifest["revision"] = current_revision + 1
            manifest["updated_at"] = now
            manifest.setdefault("history", []).append({
                "action": "withdrawn",
                "revision": manifest["revision"],
                "at": now,
                "reason": reason,
            })

        manifest = self.store.mutate(stage_id, update)
        return {
            "stage_id": manifest["stage_id"],
            "display_name": manifest["display_name"],
            "status": self._status(manifest),
            "revision": manifest["revision"],
        }

    def audit_staged_changes(self, *args, **kwargs):
        from .staged_audit import audit_staged_changes as _audit

        return _audit(self.store, *args, **kwargs)

    audit = audit_staged_changes
    audit_pending = audit_staged_changes
    audit_pending_stages = audit_staged_changes
    audit_stages = audit_staged_changes
    audit_staged = audit_staged_changes
    staged_change_audit = audit_staged_changes
    audit_staged_change = audit_staged_changes


    @staticmethod
    def _lookup_artist_names(
        token: Optional[str] = None,
        mb_recording_id: Optional[str] = None,
    ) -> Optional[List[str]]:
        if mb_recording_id:
            match = resolve_match_for_recording(mb_recording_id)
            if match and isinstance(match.get("artist_names"), list):
                return list(match["artist_names"])
        if token:
            match = resolve_match_for_token(token)
            if match and isinstance(match.get("artist_names"), list):
                if not mb_recording_id or match.get("recording_id") == mb_recording_id:
                    return list(match["artist_names"])
        return None

    @staticmethod
    def _validate_mbid(field: str, value: str) -> None:
        try:
            uuid.UUID(value.strip())
        except (TypeError, ValueError, AttributeError):
            raise ValueError(
                f"{field} must be a MusicBrainz UUID or empty to clear it."
            ) from None

    @staticmethod
    def _status(manifest: dict) -> str:
        if manifest.get("applied"):
            return "applied"
        if manifest.get("withdrawn"):
            return "withdrawn"
        if manifest.get("archived"):
            return "archived"
        if manifest.get("failed"):
            return "failed"
        return "pending"

    @classmethod
    def _require_pending(cls, manifest: dict) -> None:
        status = cls._status(manifest)
        if status != "pending":
            raise ValueError(
                f"Only pending stages can be amended or withdrawn (status: {status})."
            )

# Module-level singleton — lazily initialised on first access
_staging_manager: Optional[StagingManager] = None


def get_staging_manager() -> StagingManager:
    global _staging_manager
    if _staging_manager is None:
        _staging_manager = StagingManager()
    return _staging_manager


def annotate_staged_change(manager, stage_id, note=None, rationale=None, notes=None, expected_revision=None, reason=None):
    if notes is None:
        notes = note
    if rationale is not None:
        notes = (str(notes).strip() + ", " + str(rationale).strip()).strip() if notes else str(rationale).strip()
    if notes is None:
        raise ValueError("note must be provided.")
    notes = str(notes).strip()
    if not notes:
        raise ValueError("note must not be empty.")
    if len(notes) > 2000:
        raise ValueError("note must be at most 2000 characters.")
    without_urls = __import__("re").sub(r"https?://\S+", "", notes)
    if _LOCAL_PATH.search(without_urls):
        raise ValueError("note must not contain local filesystem paths.")

    def update(manifest):
        if expected_revision is not None:
            current_revision = manifest.get("revision", 1)
            if expected_revision != current_revision:
                raise ValueError("Stage revision changed; read the stage again. Current revision is %d." % current_revision)
        current_revision = manifest.get("revision", 1)
        if expected_revision is not None and expected_revision != current_revision:
            raise ValueError("Stage revision changed; read the stage again. Current revision is %d." % current_revision)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        manifest["notes"] = notes
        manifest["note"] = notes
        manifest["rationale"] = notes
        manifest["revision"] = current_revision + 1
        manifest["updated_at"] = now
        manifest.setdefault("history", []).append({"action": "annotated", "revision": manifest["revision"], "at": now, "reason": reason or notes})

    manifest = manager.store.mutate(stage_id, update)
    return _path_free({"stage_id": manifest["stage_id"], "display_name": manifest["display_name"], "status": manager._status(manifest), "revision": manifest.get("revision", 1), "notes": manifest.get("notes", "")})
