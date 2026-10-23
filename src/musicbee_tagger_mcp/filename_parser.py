"""Filename clue extractor for forensic track resolution.

Extracts track numbers, artist guesses, title guesses, years, and bracketed
clues (e.g. regional markers, live venues, catalog numbers) from bare filenames.
Operates on display names only (no directory paths).
"""

import re
from typing import Dict, Any, List, Optional


# Regex patterns for brackets: (), [], 【】, （）, 「」
BRACKET_REGEX = re.compile(r"[\(\[\{\【\（\「]([^\)\]\}\】\）\」]+)[\)\]\}\】\）\」]")
# Regex for 4-digit years (1920-2030)
YEAR_REGEX = re.compile(r"\b(19\d\d|20[0-2]\d)\b")
# Common file extensions to strip
AUDIO_EXTS = {".mp3", ".ogg", ".flac", ".m4a", ".wav", ".aac", ".wma", ".aiff", ".opus"}


def clean_stem(filename: str) -> str:
    """Strip extension and normalize whitespace."""
    stem = filename
    for ext in AUDIO_EXTS:
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
            break
    # Remove trailing duplicate suffixes like _1, _2
    stem = re.sub(r"_\d+$", "", stem)
    return stem.strip()


def extract_clues_from_filename(filename: str) -> Dict[str, Any]:
    """
    Parse a bare filename into structured investigative signals.
    Does not use or expose directory paths.
    """
    raw_stem = clean_stem(filename)

    # 1. Extract bracketed segments
    brackets = BRACKET_REGEX.findall(raw_stem)
    cleaned_stem = BRACKET_REGEX.sub(" ", raw_stem)
    cleaned_stem = re.sub(r"\s+", " ", cleaned_stem).strip()

    # 2. Extract year if present in brackets or text
    detected_year: Optional[str] = None
    year_match = YEAR_REGEX.search(raw_stem)
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

    # 4. Attempt Artist / Title separation
    # Common separators: " - ", " – ", " — ", " _ "
    parts = re.split(r"\s+[\-\–\—\_]\s+", cleaned_stem)
    artist_guess: Optional[str] = None
    title_guess: Optional[str] = None

    if len(parts) >= 2:
        artist_guess = parts[0].strip()
        title_guess = parts[1].strip()
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

    return {
        "raw_filename": filename,
        "cleaned_stem": cleaned_stem,
        "track_number_guess": track_num,
        "artist_guess": artist_guess,
        "title_guess": title_guess,
        "year_guess": detected_year,
        "bracket_clues": context_clues,
    }
