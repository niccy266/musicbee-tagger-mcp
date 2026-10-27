"""MusicBrainz validation for proposed artist splits.

The OpenRouter agent uses these tools to confirm that every artist produced
by a split exists as a MusicBrainz artist entity and is actually credited on
the recording/release in question — turning a mechanical pattern split into
an evidence-backed one.
"""

from __future__ import annotations

import re

from typing import Any, Dict, List

import musicbrainzngs

from .artist_split import split_artists

musicbrainzngs.set_useragent("musicbee-tagger-mcp", "0.4.5", "niccy266@gmail.com")


def propose_split(
    artist_field: str,
    split_ampersand: bool = False,
    split_comma: bool = False,
) -> Dict[str, Any]:
    """Mechanically split an artist field into candidate artists.

    Returns the candidate list plus the joiners that were recognized, so the
    agent can reason about how confident the mechanical pass is.
    """
    candidates = split_artists(artist_field, split_ampersand, split_comma)
    return {
        "input": artist_field,
        "candidates": candidates,
        "joiners_found": sorted({
            marker for marker in ("feat", "ft", "featuring", "with", "vs", "x",
                                  "semicolon", "ampersand", "comma")
            if marker.lower() in artist_field.lower() or (
                marker == "semicolon" and ";" in artist_field)
        }),
        "changed": len(candidates) > 1,
    }


def search_artist(name: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Look up artists on MusicBrainz; empty list means the name is unknown."""
    try:
        results = musicbrainzngs.search_artists(artist=name, limit=limit)
    except Exception as error:
        return [{"error": f"MusicBrainz query error: {error}"}]
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
        return {"error": f"MusicBrainz fetch error: {error}"}

    credited: List[str] = []
    for credit in rec.get("artist-credit", []):
        name = credit.get("artist", {}).get("name") or credit.get("name", "")
        if name:
            credited.append(name)
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
