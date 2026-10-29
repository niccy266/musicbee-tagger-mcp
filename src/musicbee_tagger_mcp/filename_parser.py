"""Filename clue extractor for forensic track resolution.

Extracts possible track numbers, artist/title pairs, years, and bracketed clues
(e.g. regional markers, live venues, catalog numbers) from bare filenames.
Artist/title pairs are unverified hypotheses: separators do not establish which
side is the artist, and filename text is only a clue for further research.
May also receive up to two levels of relative path context (parent folders),
which are preserved as hints without exposing absolute paths.
"""

import re
from typing import Dict, Any, List, Optional


def _path_components(filename: str) -> List[str]:
    """Split a (possibly relative) path into components on both separators."""
    text = filename.replace("\\", "/")
    return [part for part in text.split("/") if part not in ("", ".")]


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
    Parse a bare filename or a short relative path (up to two parent levels)
    into investigative signals, not authoritative tags.

    Artist/title candidate pairs are unordered hypotheses. A separator can
    split an artist name, a title, or unrelated filename text; corroborate
    candidates with track metadata, duration, and release track listings.
    Up to two parent-folder components are preserved as path context hints.
    """
    components = _path_components(filename)
    folder_components = components[:-1] if len(components) > 1 else []
    # Limit to two levels of relative path context.
    if len(folder_components) > 2:
        folder_components = folder_components[-2:]
    basename = components[-1] if components else filename

    raw_stem = clean_stem(basename)

    # 1. Extract bracketed segments
    brackets = BRACKET_REGEX.findall(raw_stem)
    cleaned_stem = BRACKET_REGEX.sub(" ", raw_stem)
    cleaned_stem = re.sub(r"\s+", " ", cleaned_stem).strip()

    # 2. Extract year if present in brackets or text
    detected_year: Optional[str] = None
    year_match = YEAR_REGEX.search(raw_stem)
    if year_match:
        detected_year = year_match.group(1)
    # Fall back to a year encoded in the (up to two) parent folder names.
    if detected_year is None:
        for folder in folder_components:
            folder_year = YEAR_REGEX.search(folder)
            if folder_year:
                detected_year = folder_year.group(1)
                break

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

    # Preserve country/region context from parent folders as hints.
    for folder in folder_components:
        folder_clean = folder.strip()
        if not folder_clean:
            continue
        if YEAR_REGEX.fullmatch(folder_clean):
            continue
        if folder_clean.lower() in ("flac", "mp3", "320", "vbr", "remaster", "remastered", "stereo", "mono"):
            continue
        if folder_clean not in context_clues:
            context_clues.append(folder_clean)

    relative_path = "/".join(components) if components else filename
    folder_list = list(folder_components)

    result: Dict[str, Any] = {
        "raw_filename": filename,
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
    }

    # Preserve the relative path context under several hint-style aliases so
    # country/year compilation context survives regardless of the consumer's
    # expected field name.
    for key in (
        "relative_path",
        "relative_filepath",
        "relative_path_hint",
        "filepath_hint",
        "filename_hint",
        "path_hint",
    ):
        result[key] = relative_path
    for key in (
        "folder_clues",
        "path_clues",
        "directory_clues",
        "path_context",
        "folder_context",
        "directory_context",
        "folder_names",
        "parent_dirs",
        "parent_folders",
    ):
        result[key] = folder_list

    return result
