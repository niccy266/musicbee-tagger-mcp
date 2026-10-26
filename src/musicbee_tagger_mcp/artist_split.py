"""Split malformed artist fields into multiple artists.

Navidrome and other Subsonic-family servers use multi-value artist tags to
group tracks by every contributing artist. Files tagged ``Kendrick Lamar
feat. Lil Nas X`` in one string only surface under the first artist.

This module detects common joiner patterns and produces a clean artist list.
The canonical staging field keeps a semicolon-joined string for display; the
format writers accept a real list of artists and emit native multi-value
tags (ID3v2.4 repeated text frames, Vorbis repeated keys, MP4 string lists).

Deliberate scope: only *featured-artist* markers split by default
(``feat.``, ``ft.``, ``featuring``, ``with``, ``vs.``, ``x``/``×``,
``&`` between names that are not a known one-word-pair hazard). Plain ``&``
is ambiguous — ``Mumford & Sons`` and ``Earth, Wind & Fire`` are single
artists — so ampersand splitting is opt-in via ``split_ampersand=True``.
"""

from __future__ import annotations

import re
from typing import List

# Explicit featured-artist markers, most specific first. Word boundaries on
# both sides prevent matching "feat" inside words; optional trailing dots.
_FEATURED_RE = re.compile(
    # Word markers must be followed by at least one non-space character.
    r"""\s*(?:,\s*)?(?:\bfeat(?:uring|\.?)|\bft\.|\bwith\b|\bvs\.)\s+(?=\S)""",
    re.IGNORECASE,
)
_X_RE = re.compile(r"\s+(?:x|×)\s+", re.IGNORECASE)
# A separator already usable as a multi-value boundary.
_SEMICOLON_RE = re.compile(r"\s*;\s*")
# "A & B" / "A and B" — ambiguous, opt-in.
_AMPERSAND_RE = re.compile(r"\s+(?:&|and)\s+", re.IGNORECASE)
_COMMA_RE = re.compile(r"\s*,\s*")


def split_artists(
    value: str,
    split_ampersand: bool = False,
    split_comma: bool = False,
) -> List[str]:
    """Split an artist string into a list of artist names.

    Args:
        value: raw artist field contents (may contain "feat.", "&", ";", ...).
        split_ampersand: also split on " & " / " and " (ambiguous: breaks
            band names like "Mumford & Sons" — opt in knowingly).
        split_comma: also split on commas ("Artist A, Artist B" lists).

    Returns:
        Ordered, de-duplicated (case-insensitively), whitespace-trimmed names.
        A value with no recognized joiner returns as a one-item list unchanged.
    """
    if not value or not value.strip():
        return []
    text = value.strip()
    # Existing semicolons are authoritative boundaries first.
    parts: List[str] = []
    for chunk in _SEMICOLON_RE.split(text):
        parts.extend(_split_chunk(chunk, split_ampersand, split_comma))
    return _dedupe_preserve_order(parts)


def _split_chunk(chunk: str, split_ampersand: bool, split_comma: bool) -> List[str]:
    text = chunk.strip()
    if not text:
        return []
    # Pass one: word markers (feat., ft., with, vs.).
    pieces: List[str] = _FEATURED_RE.split(text)
    # Pass two: standalone "x"/"×", only where both sides stay non-empty,
    # so names ending in "X" (Lil Nas X) are never broken. An "x" that
    # directly precedes a word marker is part of the preceding name.
    pieces = [p for piece in pieces for p in _split_x(piece)]
    if split_ampersand:
        pieces = [p for piece in pieces
                  for p in _AMPERSAND_RE.split(piece)]
    if split_comma:
        pieces = [p for piece in pieces
                  for p in _COMMA_RE.split(piece)]
    return [p.strip(" \t-–—") for p in pieces if p and p.strip()]


def _split_x(piece: str) -> List[str]:
    parts = _X_RE.split(piece.strip(), maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts
    return [piece]


def _dedupe_preserve_order(names: List[str]) -> List[str]:
    seen: set = set()
    result: List[str] = []
    for name in names:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            result.append(name)
    return result


def join_artists(names: List[str]) -> str:
    """Render an artist list as the canonical semicolon-joined string."""
    return "; ".join(names)


def needs_split(value: str) -> bool:
    """True when the field contains a featured-artist marker worth splitting."""
    return len(split_artists(value)) > 1
