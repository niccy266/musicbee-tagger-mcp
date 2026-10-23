"""Shared release classification and candidate comparison helpers."""

import difflib
import re
from typing import Any, Dict, Optional


def classify_release(release: Dict[str, Any]) -> Dict[str, Any]:
    """Classify release type conservatively when group data is absent."""
    title = release.get("title", "")
    group = release.get("release-group", {})
    primary_type = group.get("primary-type", "Unknown")
    secondary_types = group.get("secondary-type-list", [])
    is_live = "Live" in secondary_types or "live" in title.lower()
    is_compilation = "Compilation" in secondary_types or "compilation" in title.lower()

    category = "Unknown"
    if is_live:
        category = "Live Release"
    elif is_compilation:
        category = "Compilation"
    elif primary_type in ("Single", "EP"):
        category = "Single / EP"
    elif primary_type == "Album":
        category = "Studio Album"

    return {
        "category": category,
        "is_live": is_live,
        "is_compilation": is_compilation,
        "primary_type": primary_type,
        "secondary_types": secondary_types,
    }


def calculate_duration_score(
    target_sec: Optional[float], mb_length_ms: Optional[int]
) -> tuple[float, str]:
    """Score how closely a MusicBrainz duration matches the local track."""
    if not target_sec or not mb_length_ms:
        return 0.0, "no_duration_data"
    diff = abs(target_sec - mb_length_ms / 1000.0)
    if diff <= 2.5:
        return 30.0, f"exact_match (diff {diff:.1f}s)"
    if diff <= 6.0:
        return 20.0, f"close_match (diff {diff:.1f}s)"
    if diff <= 15.0:
        return 5.0, f"approximate (diff {diff:.1f}s)"
    return -25.0, f"duration_mismatch (diff {diff:.1f}s)"


def string_similarity(a: Optional[str], b: Optional[str]) -> float:
    """Compare normalized strings while tolerating bracketed title qualifiers."""
    if not a or not b:
        return 0.0
    first, second = a.strip().lower(), b.strip().lower()
    if first == second:
        return 1.0
    clean_first = re.sub(r"[\(\[\{\【\（\「].*?[\)\]\}\】\）\」]", "", first).strip()
    clean_second = re.sub(r"[\(\[\{\【\（\「].*?[\)\]\}\】\）\」]", "", second).strip()
    if clean_first and clean_second and clean_first == clean_second:
        return 0.95
    base = difflib.SequenceMatcher(None, first, second).ratio()
    cleaned = difflib.SequenceMatcher(
        None, clean_first or first, clean_second or second
    ).ratio()
    return round(max(base, cleaned), 3)
