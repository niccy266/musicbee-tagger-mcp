"""MusicBrainz validation for proposed artist splits.

The OpenRouter agent uses these tools to confirm that every artist produced
by a split exists as a MusicBrainz artist entity and is actually credited on
the recording/release in question — turning a mechanical pattern split into
an evidence-backed one.
"""

from __future__ import annotations

import re

from typing import Any, Dict, List, Optional

import musicbrainzngs

from .artist_credit import credit_names, normalize_artist_value
from .error_codes import redact_paths
from .artist_split import split_artists

musicbrainzngs.set_useragent("musicbee-tagger-mcp", "0.4.6", "niccy266@gmail.com")


def propose_split(
    artist_field: str,
    split_ampersand: bool = False,
    split_comma: bool = False,
    recording_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Mechanically split an artist field into candidate artists and tag_value.

    Returns the candidate list, the '; '-formatted tag_value, any warnings,
    and the joiners that were recognized. When recording_id is given, fetches
    its MusicBrainz artist credits once and uses them to normalize without
    splitting single acts like 'Earth, Wind & Fire'.
    """
    candidates = split_artists(artist_field, split_ampersand, split_comma)
    credited: Optional[List[str]] = None
    if recording_id:
        credit_info = verify_artist_credit(recording_id, candidates)
        if "error" not in credit_info:
            credited = credit_info.get("credited_names") or None
    tag_value, warnings = normalize_artist_value(artist_field, credited)
    if credited and isinstance(tag_value, str) and len(credited) >= 2:
        split_from_tag = [p.strip() for p in tag_value.split(";") if p.strip()]
        if len(split_from_tag) > 1:
            candidates = split_from_tag
    return {
        "input": artist_field,
        "candidates": candidates,
        "tag_value": tag_value,
        "warnings": warnings,
        "joiners_found": sorted({
            marker for marker in ("feat", "ft", "featuring", "with", "vs", "x",
                                  "semicolon", "ampersand", "comma")
            if marker.lower() in artist_field.lower() or (
                marker == "semicolon" and ";" in artist_field)
        }),
        "changed": tag_value != artist_field or len(candidates) > 1,
    }


def search_artist(name: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Look up artists on MusicBrainz; empty list means the name is unknown."""
    try:
        results = musicbrainzngs.search_artists(artist=name, limit=limit)
    except Exception as error:
        return [{"error": redact_paths(f"MusicBrainz query error: {error}")}]
    out = []
    for a in results.get("artist-list", []):
        out.append({
            "artist_id": a.get("id"),
            "name": a.get("name"),
            "score": a.get("ext:score"),
            "disambiguation": a.get("disambiguation", ""),
            "type": a.get("type", ""),
            "area": (a.get("area") or {}).get("name", ""),
        })
    return out


def verify_artist_credit(
    recording_id: str,
    candidate_artists: List[str],
) -> Dict[str, Any]:
    """Check each candidate artist appears in the recording's artist credits.

    Fetches the canonical recording with its artist credit relation, then
    matches every candidate name against credited names (exact, then
    case-insensitive, then substring). Returns per-candidate verdicts the
    agent treats as evidence, not commands.
    """
    try:
        rec = musicbrainzngs.get_recording_by_id(
            recording_id, includes=["artist-credits"])["recording"]
    except Exception as error:
        return {"error": redact_paths(f"MusicBrainz fetch error: {error}")}

    credited = credit_names(rec.get("artist-credit", []))
    credited_join = rec.get("artist-credit-phrase", "")

    verdicts = []
    for candidate in candidate_artists:
        low = candidate.casefold()
        match = next((n for n in credited if n.casefold() == low), None)
        match_type = "exact" if match else None
        if not match:
            sub = next((n for n in credited if low in n.casefold()
                        or n.casefold() in low), None)
            if sub:
                match, match_type = sub, "partial"
        verdicts.append({
            "candidate": candidate,
            "credited": match is not None,
            "match_type": match_type,
            "matched_name": match,
        })
    return {
        "recording_id": recording_id,
        "canonical_title": rec.get("title", ""),
        "credited_join": credited_join,
        "credited_names": credited,
        "verdicts": verdicts,
        "all_verified": all(v["credited"] for v in verdicts),
    }


def propose_artist_split(
    artist_field: str,
    split_ampersand: bool = False,
    split_comma: bool = False,
    recording_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compatibility alias matching the MCP tool name."""
    return propose_split(
        artist_field,
        split_ampersand=split_ampersand,
        split_comma=split_comma,
        recording_id=recording_id,
    )


def flag_suspicious_artists(candidate_artists: List[str]) -> List[Dict[str, str]]:
    """Compatibility alias matching the MCP tool name."""
    return heuristic_flags(candidate_artists)


def heuristic_flags(candidates: List[str]) -> List[Dict[str, str]]:
    """Cheap sanity flags the agent weighs with its own judgment."""
    flags = []
    for name in candidates:
        notes = []
        if len(name) <= 2 and not name.isupper():
            notes.append("suspiciously short — possible garbled split")
        if sum(c.isupper() for c in name if c.isalpha()) > 1 and \
                not name.isupper() and not name.istitle():
            notes.append("irregular casing — possible mojibake or debris")
        if "  " in name or name != name.strip():
            notes.append("whitespace debris")
        if any(0xE000 <= ord(c) <= 0xF8FF for c in name) or re.search(
            "Ã[^\x20-\x7e]", name):
            notes.append("mojibake pattern — likely encoding debris")
        if notes:
            flags.append({"artist": name, "flags": "; ".join(notes)})
    return flags
