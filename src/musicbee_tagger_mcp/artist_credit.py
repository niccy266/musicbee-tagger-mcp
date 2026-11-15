"""Helpers for MusicBrainz artist credits and semicolon-separated artist tags."""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from .artist_split import join_artists, split_artists

_JOIN_TOKENS_ONLY_RE = re.compile(
    r"^[\s,&+/;]*(?:(?:feat\.?|ft\.?|featuring|with|vs\.?|versus|and|x)\b[\s,&+/;]*)*$",
    re.IGNORECASE,
)

_UNSPLIT_JOINER_WARNING_RE = re.compile(
    r"(?:\S\s+(?:&|and)\s+\S|\w\s*,\s*\S)",
    re.IGNORECASE,
)

UNSPLIT_ARTIST_WARNING = (
    "artist contains '&'/'and'/',': confirm whether this is one act or several"
)
SEMICOLON_IN_NAME_WARNING = (
    "credited artist name contains ';': MusicBee may treat it as multiple artists"
)


def credit_names(artist_credit: Optional[Iterable[Any]]) -> List[str]:
    """Extract ordered, deduplicated artist names from a MusicBrainz artist-credit list."""
    if not artist_credit or isinstance(artist_credit, (str, bytes, dict)):
        return []

    names: List[str] = []
    seen_lower: set[str] = set()
    for entry in artist_credit:
        if not isinstance(entry, dict):
            continue
        raw_name = ""
        artist_dict = entry.get("artist")
        if isinstance(artist_dict, dict):
            raw_name = str(artist_dict.get("name") or "").strip()
        if not raw_name:
            raw_name = str(entry.get("name") or "").strip()
        if not raw_name:
            continue
        key = raw_name.casefold()
        if key not in seen_lower:
            seen_lower.add(key)
            names.append(raw_name)
    return names


def artist_tag_value(names: Sequence[str]) -> str:
    """Format artist names as a '; '-separated MusicBee tag value."""
    cleaned = [str(n).strip() for n in (names or []) if isinstance(n, str) and str(n).strip()]
    return join_artists(cleaned)


def _composed_of_credited_names(proposed: str, credited: Sequence[str]) -> bool:
    """Return True when proposed consists of all credited names plus only join text."""
    remaining = proposed
    for name in sorted(credited, key=len, reverse=True):
        pattern = re.compile(re.escape(name), re.IGNORECASE)
        remaining, count = pattern.subn(" ", remaining, count=1)
        if count == 0:
            return False
    return bool(_JOIN_TOKENS_ONLY_RE.match(remaining))


def normalize_artist_value(
    proposed: Any,
    credited_names: Optional[Sequence[str]] = None,
) -> Tuple[Any, List[str]]:
    """Normalize a proposed artist tag string to '; '-separated artists when warranted."""
    if not isinstance(proposed, str):
        return proposed, []

    stripped = proposed.strip()
    if not stripped:
        return proposed, []

    warnings: List[str] = []
    clean_credits = [
        str(n).strip()
        for n in (credited_names or [])
        if isinstance(n, str) and str(n).strip()
    ]

    if len(clean_credits) >= 2 and _composed_of_credited_names(stripped, clean_credits):
        for name in clean_credits:
            if ";" in name and SEMICOLON_IN_NAME_WARNING not in warnings:
                warnings.append(SEMICOLON_IN_NAME_WARNING)
        return artist_tag_value(clean_credits), warnings

    if len(clean_credits) == 1 and stripped.casefold() == clean_credits[0].casefold():
        if ";" in stripped:
            warnings.append(SEMICOLON_IN_NAME_WARNING)
        return proposed, warnings

    parts = split_artists(stripped)
    result = join_artists(parts) if parts else stripped

    segments = [seg.strip() for seg in result.split(";")]
    if any(_UNSPLIT_JOINER_WARNING_RE.search(seg) for seg in segments if seg):
        warnings.append(UNSPLIT_ARTIST_WARNING)

    return result, warnings
