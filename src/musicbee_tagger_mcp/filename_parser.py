"""Filename clue extractor for forensic track resolution.

Extracts possible track numbers, artist/title pairs, years, and bracketed clues
(e.g. regional markers, live venues, catalog numbers) from bare filenames.
Artist/title pairs are unverified hypotheses: separators do not establish which
side is the artist, and filename text is only a clue for further research.
Operates on display names only (no directory paths).
"""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional


# Opening/closing bracket characters handled by the parser.
_OPENING_BRACKETS = "([{【（「"
_CLOSING_BRACKETS = ")]}】）」"
# Regex for 4-digit years (1920-2030)
YEAR_REGEX = re.compile(r"\b(19\d\d|20[0-2]\d)\b")
# Common file extensions to strip
AUDIO_EXTS = {".mp3", ".ogg", ".flac", ".m4a", ".wav", ".aac", ".wma", ".aiff", ".opus"}

# Invisible Unicode format characters (bidi marks, zero-width, BOM) that carry
# no visible content and break matching.  Mirrors field_map._INVISIBLE_RE.
_INVISIBLE_RE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)


def _sanitize(text: Any) -> str:
    """Remove invisible formatting characters without altering visible text."""
    if text is None:
        return ""
    return _INVISIBLE_RE.sub("", str(text))


def _extract_bracket_contents(text: str) -> List[str]:
    """Extract top-level balanced bracket contents, preserving nested text.

    Mixed and nested brackets are handled conservatively: an outer bracket's
    full inner text (including any nested brackets) is returned as one clue,
    and unmatched brackets are left untouched in the source text.
    """
    results: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] in _OPENING_BRACKETS:
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if text[j] in _OPENING_BRACKETS:
                    depth += 1
                elif text[j] in _CLOSING_BRACKETS:
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if depth == 0 and j < n:
                results.append(text[i + 1 : j])
                i = j + 1
                continue
            # Unbalanced bracket: leave it in place.
            i += 1
        else:
            i += 1
    return results


def clean_stem(filename: str) -> str:
    """Strip extension and normalize whitespace.

    A trailing ``_N`` suffix is treated as a track number and stripped, but
    meaningful multi-digit suffixes such as ``_2020`` are preserved.
    """
    # Accept either a bare filename or a relative/absolute path; only the
    # final component is treated as the filename stem.
    stem = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
    stem = _sanitize(stem)
    for ext in AUDIO_EXTS:
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
            break
    # Remove trailing track-number suffixes like _1, _2 (but not _2020).
    stem = re.sub(r"_\d{1,3}$", "", stem)
    return stem.strip()


def extract_clues_from_filename(filename: str) -> Dict[str, Any]:
    """
    Parse a bare filename into investigative signals, not authoritative tags.

    Artist/title candidate pairs are unordered hypotheses. A separator can
    split an artist name, a title, or unrelated filename text; corroborate
    candidates with track metadata, duration, and release track listings.
    Does not use or expose directory paths.
    """
    raw_stem = clean_stem(filename)

    # Preserve up to two levels of (relative) folder context as hints without
    # exposing an absolute path.  This keeps country/year clues from layouts
    # such as "Country/Year/track.mp3".
    _parts = [_sanitize(part) for part in str(filename).replace("\\", "/").split("/") if part]
    folder_parts = _parts[-3:-1] if len(_parts) >= 2 else []
    relative_path_hint = "/".join(folder_parts + [_parts[-1]]) if _parts else str(filename)
    relative_path_hint = _sanitize(relative_path_hint)

    # 1. Extract bracketed segments (without removing them from the stem, so
    #    the full title text is preserved in candidates).
    brackets = _extract_bracket_contents(raw_stem)
    cleaned_stem = re.sub(r"\s+", " ", raw_stem).strip()

    # 2. Extract year if present in brackets or text
    detected_year: Optional[str] = None
    year_match = YEAR_REGEX.search(relative_path_hint)
    if year_match:
        detected_year = year_match.group(1)

    # 3. Check for leading track number (e.g. "01 - ...", "01. ...", "01 ...").
    #    Hyphenated titles such as "99-Luftballons" or "7-Seconds" are NOT
    #    treated as track numbers: a hyphen alone (without surrounding
    #    whitespace) does not separate a track number from its title.
    track_num: Optional[int] = None
    track_match = re.match(r"^(\d{1,3})(?:\s+[-_.]?\s*|_+|\.)(.+)$", cleaned_stem)
    if track_match:
        try:
            track_num = int(track_match.group(1))
            cleaned_stem = track_match.group(2).strip()
        except ValueError:
            pass

    # 4. Generate unranked Artist / Title hypotheses from ambiguous separators.
    # Common separators: " - ", " – ", " — ", " _ "
    parts = re.split(r"\s+[\-\–\—\_]\s+", cleaned_stem)
    artist_guess: Optional[str] = None
    title_guess: Optional[str] = None
    artist_title_candidates: List[Dict[str, str]] = []

    if len(parts) >= 2:
        first = parts[0].strip()
        second = " - ".join(part.strip() for part in parts[1:])
        artist_title_candidates = [
            {"artist": first, "title": second},
            {"artist": second, "title": first},
        ]
    elif len(parts) == 1 and cleaned_stem:
        title_guess = cleaned_stem

    # Separate bracket clues: distinguish year vs regional/subtitle notes
    context_clues: List[str] = []
    for b in brackets:
        b_clean = _sanitize(b).strip()
        if not b_clean:
            continue
        if YEAR_REGEX.fullmatch(b_clean):
            continue  # Already captured as year
        # Ignore common audio quality tags
        if b_clean.lower() in ("flac", "mp3", "320", "vbr", "remaster", "remastered", "stereo", "mono"):
            continue
        context_clues.append(b_clean)

    # Expose folder names (up to two levels) as non-path hints.
    for folder in folder_parts:
        if folder and folder.lower() not in ("flac", "mp3", "320"):
            context_clues.append(folder)

    return {
        "raw_filename": _sanitize(Path(filename).name),
        "cleaned_stem": cleaned_stem,
        "track_number_guess": track_num,
        "artist_guess": artist_guess,
        "title_guess": title_guess,
        "artist_title_candidates": artist_title_candidates,
        "artist_title_candidates_are_unverified": True,
        "artist_title_candidates_note": (
            "Unverified filename hypotheses only. Separators can split an "
            "artist name, title, or unrelated text; corroborate before using "
            "these values as tags."
        ),
        "year_guess": detected_year,
        "bracket_clues": context_clues,
        "relative_path_hint": relative_path_hint,
        "folder_context": folder_parts,
    }
