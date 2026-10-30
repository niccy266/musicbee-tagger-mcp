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


# Regex patterns for brackets: (), [], 【】, （）, 「」
BRACKET_REGEX = re.compile(r"[\(\[\{\【\（\「]([^\)\]\}\】\）\」]+)[\)\]\}\】\）\」]")
# Regex for 4-digit years (1920-2030)
YEAR_REGEX = re.compile(r"\b(19\d\d|20[0-2]\d)\b")
# Common file extensions to strip
AUDIO_EXTS = {".mp3", ".ogg", ".flac", ".m4a", ".wav", ".aac", ".wma", ".aiff", ".opus"}


def clean_stem(filename: str) -> str:
    """Strip extension and normalize whitespace."""
    # Accept either a bare filename or a relative/absolute path; only the
    # final component is treated as the filename stem.
    stem = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
    for ext in AUDIO_EXTS:
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
            break
    # Remove trailing duplicate suffixes like _1, _2
    stem = re.sub(r"_\d+$", "", stem)
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
    _parts = [part for part in str(filename).replace("\\", "/").split("/") if part]
    folder_parts = _parts[-3:-1] if len(_parts) >= 2 else []
    relative_path_hint = "/".join(folder_parts + [_parts[-1]]) if _parts else str(filename)

    # 1. Extract bracketed segments
    brackets = BRACKET_REGEX.findall(raw_stem)
    cleaned_stem = BRACKET_REGEX.sub(" ", raw_stem)
    cleaned_stem = re.sub(r"\s+", " ", cleaned_stem).strip()

    # 2. Extract year if present in brackets or text
    detected_year: Optional[str] = None
    year_match = YEAR_REGEX.search(relative_path_hint)
    if year_match:
        detected_year = year_match.group(1)

    # 3. Check for leading track number (e.g. "01 - ...", "01. ...", "01 ...")
    track_num: Optional[int] = None
    track_match = re.match(r"^(\d{1,3})[\s\.\-_]+(.+)$", cleaned_stem)
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
        b_clean = b.strip()
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

    _normalized = str(filename).replace("\\", "/")
    _basename = _normalized.rsplit("/", 1)[-1] if _normalized else str(filename)
    return {
        "raw_filename": _basename,
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
