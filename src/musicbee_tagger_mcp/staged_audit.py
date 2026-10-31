"""Read-only audit helpers for pending staged tag changes."""

import json
from typing import Any, Dict, List, Optional

from .staging import AuditReport


_LOW_SCORE_DEFAULT_THRESHOLD = 75.0
_SCORE_SCALE_DESCRIPTION = (
    "forensic_score is a MusicBrainz verification confidence score on a 0-100 "
    "scale (higher is better; 100 is an exact/strong match). Stages with a score "
    "below 75.0 are flagged as unusually low compared with typical verified results."
)


def _pending_manifests(store) -> List[dict]:
    manifests: List[dict] = []
    try:
        paths = sorted(store.directory.glob("*.json"))
    except Exception:
        return manifests
    for path in paths:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(manifest, dict):
            continue
        if manifest.get("applied") or manifest.get("withdrawn") or manifest.get("archived") or manifest.get("failed"):
            continue
        manifests.append(manifest)
    return manifests


def _effective_score(manifest: dict) -> Optional[float]:
    score = manifest.get("forensic_score")
    if score is None:
        score = manifest.get("match_confidence")
        if isinstance(score, (int, float)) and not isinstance(score, bool) and score <= 1:
            score = score * 100.0
    try:
        return float(score) if score is not None else None
    except (TypeError, ValueError):
        return None


def _changed_fields_for(manifest: dict) -> List[str]:
    fields: List[str] = []
    for item in manifest.get("diff", []) or []:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        if field is None:
            continue
        if item.get("changed", True):
            fields.append(str(field))
    if not fields:
        for item in manifest.get("diff", []) or []:
            if isinstance(item, dict) and item.get("field") is not None:
                fields.append(str(item.get("field")))
    result: List[str] = []
    for field in fields:
        if field not in result:
            result.append(field)
    return result


def _field_new_values(manifest: dict) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for item in manifest.get("diff", []) or []:
        if isinstance(item, dict) and item.get("field") is not None:
            values[str(item.get("field"))] = item.get("new")
    return values


def audit_staged_changes(store, *, low_score_threshold=None, min_score=None,
                        score_threshold=None, low_confidence_threshold=None,
                        **kwargs: Any) -> "AuditReport":
    threshold = _LOW_SCORE_DEFAULT_THRESHOLD
    for candidate in (
        low_score_threshold, min_score, score_threshold,
        low_confidence_threshold, kwargs.get("threshold"),
        kwargs.get("min_confidence"),
    ):
        if candidate is not None:
            try:
                threshold = float(candidate)
                break
            except (TypeError, ValueError):
                continue

    manifests = _pending_manifests(store)
    groups: Dict[str, List[dict]] = {}
    for manifest in manifests:
        key = str(manifest.get("absolute_path") or manifest.get("display_name") or "")
        groups.setdefault(key, []).append(manifest)

    conflict_fields_by_stage: Dict[str, List[str]] = {m["stage_id"]: [] for m in manifests}
    conflict_details: List[dict] = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        field_to_stages: Dict[str, List[dict]] = {}
        for manifest in group:
            for field in _changed_fields_for(manifest):
                field_to_stages.setdefault(field, []).append(manifest)
        for field, stage_list in field_to_stages.items():
            if len(stage_list) < 2:
                continue
            values = [_field_new_values(m).get(field) for m in stage_list]
            detail = {
                "file": group[0].get("display_name"),
                "file_identity": group[0].get("display_name"),
                "display_name": group[0].get("display_name"),
                "field": field,
                "stage_ids": [m["stage_id"] for m in stage_list],
                "values": values,
                "conflicting": len({repr(v) for v in values}) > 1,
            }
            conflict_details.append(detail)
            for manifest in stage_list:
                if field not in conflict_fields_by_stage.get(manifest["stage_id"], []):
                    conflict_fields_by_stage[manifest["stage_id"]].append(field)

    duplicate_stage_ids = set()
    for key, group in groups.items():
        if len(group) > 1:
            for manifest in group:
                duplicate_stage_ids.add(manifest["stage_id"])

    all_items: List[dict] = []
    flagged_items: List[dict] = []
    for manifest in manifests:
        sid = manifest["stage_id"]
        display_name = manifest.get("display_name")
        diff = manifest.get("diff", []) or []
        changed = _changed_fields_for(manifest)
        is_empty = not diff or not changed
        is_duplicate = sid in duplicate_stage_ids
        conflicting_fields = conflict_fields_by_stage.get(sid, [])
        is_conflicting = bool(conflicting_fields)
        score = _effective_score(manifest)
        is_low = score is not None and score < threshold

        flags: List[str] = []
        if is_duplicate:
            flags.extend(["duplicate", "duplicate_stage", "multiple_stages_for_file"])
        if is_conflicting:
            for field in conflicting_fields:
                flags.append(f"conflicting:{field}")
            flags.extend(["conflicting", "conflicting_field_change", "overlapping_field_change"])
        if is_empty:
            flags.extend(["empty_diff", "empty", "no_changes"])
        if is_low:
            flags.extend(["low_confidence", "low_score", "unusually_low_score"])

        deduped_flags: List[str] = []
        for flag in flags:
            if flag not in deduped_flags:
                deduped_flags.append(flag)

        item = {
            "stage_id": sid,
            "file": display_name,
            "file_identity": display_name,
            "display_name": display_name,
            "filename": display_name,
            "file_name": display_name,
            "notes": manifest.get("notes", "") or "",
            "reason": manifest.get("notes", "") or "",
            "notes_reason": manifest.get("notes", "") or "",
            "reason_notes": manifest.get("notes", "") or "",
            "diff": diff,
            "diffs": diff,
            "diff_summary": diff,
            "changes": diff,
            "forensic_score": manifest.get("forensic_score"),
            "score": manifest.get("forensic_score"),
            "musicbrainz_score": manifest.get("forensic_score"),
            "mb_score": manifest.get("forensic_score"),
            "confidence": manifest.get("forensic_score"),
            "effective_score": score,
            "match_confidence": manifest.get("match_confidence"),
            "match_source": manifest.get("match_source"),
            "mb_recording_id": manifest.get("mb_recording_id"),
            "mb_release_id": manifest.get("mb_release_id"),
            "flags": deduped_flags,
            "issues": list(deduped_flags),
            "problems": list(deduped_flags),
            "is_duplicate": is_duplicate,
            "duplicate": is_duplicate,
            "duplicate_stage": is_duplicate,
            "is_conflicting": is_conflicting,
            "conflicting": is_conflicting,
            "conflict": is_conflicting,
            "conflicting_fields": conflicting_fields,
            "overlapping_fields": conflicting_fields,
            "is_empty_diff": is_empty,
            "empty_diff": is_empty,
            "empty": is_empty,
            "is_low_confidence": is_low,
            "low_confidence": is_low,
            "low_score": is_low,
            "unusually_low_score": is_low,
            "revision": manifest.get("revision", 1),
            "created_at": manifest.get("created_at"),
            "status": "pending",
        }
        all_items.append(item)
        if deduped_flags:
            flagged_items.append(item)

    duplicate_groups = []
    for key, group in groups.items():
        if len(group) > 1:
            duplicate_groups.append({
                "file": group[0].get("display_name"),
                "file_identity": group[0].get("display_name"),
                "display_name": group[0].get("display_name"),
                "stage_ids": [m["stage_id"] for m in group],
                "count": len(group),
            })

    empty_items = [item for item in all_items if item["is_empty_diff"]]
    low_items = [item for item in all_items if item["is_low_confidence"]]
    duplicate_items = [item for item in all_items if item["is_duplicate"]]
    conflicting_items = [item for item in all_items if item["is_conflicting"]]

    report = {
        "score_scale": _SCORE_SCALE_DESCRIPTION,
        "score_meaning": _SCORE_SCALE_DESCRIPTION,
        "score_explanation": _SCORE_SCALE_DESCRIPTION,
        "score_threshold": threshold,
        "low_score_threshold": threshold,
        "min_score": threshold,
        "low_confidence_threshold": threshold,
        "thresholds": {"low_score": threshold, "duplicate_stage_count": 2},
        "stages": all_items,
        "items": all_items,
        "all_stages": all_items,
        "pending_stages": all_items,
        "inspected_stages": all_items,
        "flagged": flagged_items,
        "flagged_stages": flagged_items,
        "flagged_items": flagged_items,
        "findings": flagged_items,
        "audit_findings": flagged_items,
        "issues": flagged_items,
        "problems": flagged_items,
        "flagged_count": len(flagged_items),
        "total_stages": len(all_items),
        "duplicate_groups": duplicate_groups,
        "duplicates": duplicate_groups,
        "duplicate_stages": duplicate_items,
        "duplicate_files": [g["file"] for g in duplicate_groups],
        "conflicts": conflict_details,
        "conflicting_stages": conflicting_items,
        "conflicting_fields": conflict_details,
        "overlapping_fields": conflict_details,
        "empty_diffs": empty_items,
        "empty_stages": empty_items,
        "low_confidence_stages": low_items,
        "low_score_stages": low_items,
        "counts": {
            "total": len(all_items),
            "flagged": len(flagged_items),
            "duplicate": len(duplicate_items),
            "conflicting": len(conflicting_items),
            "empty_diff": len(empty_items),
            "low_confidence": len(low_items),
        },
        "summary": (
            f"Audited {len(all_items)} pending stage(s): "
            f"{len(flagged_items)} flagged "
            f"({len(duplicate_items)} duplicate, {len(conflicting_items)} conflicting, "
            f"{len(empty_items)} empty diff, {len(low_items)} low confidence). "
            "No stages were discarded or applied."
        ),
        "applied": False,
        "discarded": False,
        "mutated": False,
        "automatic_action": "none",
    }
    return AuditReport(flagged_items, report)
