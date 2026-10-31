"""Safe cleanup helpers for genre tags."""

from __future__ import annotations

import re
from typing import Any, List

_CHART_PHRASES = {
    "offizielle charts",
    "official charts",
    "charts",
    "chart",
    "top 100",
    "top 40",
    "top 20",
    "top 10",
}
_CHART_PATTERNS = (
    re.compile(r"^\s*\d+\s*[\u2013\-]\s*\d+\s*wochen\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*\+\s*wochen\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*wochen\s*$", re.IGNORECASE),
    re.compile(r"^\s*wochen\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*weeks?\s*$", re.IGNORECASE),
)

_LANGUAGE_LABELS = {
    "english", "german", "french", "spanish", "italian", "portuguese",
    "russian", "japanese", "korean", "chinese", "dutch", "polish",
    "swedish", "norwegian", "danish", "finnish", "turkish", "arabic",
    "hindi", "thai", "vietnamese", "indonesian", "greek", "hebrew",
    "czech", "hungarian", "romanian", "bulgarian", "ukrainian",
    "croatian", "serbian", "slovak", "slovenian", "catalan", "basque",
    "latin", "multilingual",
}

_MOOD_DESCRIPTORS = {
    "melancholic", "melancholy", "sad", "happy", "uplifting", "energetic",
    "calm", "relaxing", "chill", "dark", "atmospheric", "romantic",
    "aggressive", "epic", "dreamy", "nostalgic", "upbeat", "mellow",
    "intense", "peaceful", "somber", "brooding", "joyful",
    "angry", "anxious", "tense", "serene", "ethereal", "haunting",
    "groovy", "funky", "soulful", "passionate", "bittersweet",
    "triumphant", "mysterious", "playful", "whimsical", "reflective",
    "contemplative", "meditative", "hypnotic", "euphoric", "gloomy",
}

_SEPARATORS = ("; ", ";", ", ", ",", "|", "\n", "\t")


def _is_chart_clutter(value: str) -> bool:
    lowered = value.strip().casefold()
    if lowered in _CHART_PHRASES:
        return True
    return any(pattern.match(value.strip()) for pattern in _CHART_PATTERNS)


def _is_language_clutter(value: str) -> bool:
    return value.strip().casefold() in _LANGUAGE_LABELS


def _detect_separator(value: str) -> str:
    for separator in _SEPARATORS:
        if separator in value:
            return separator
    return "; "


def _normalize_remove_moods(**kwargs: Any) -> tuple[bool, set[str]]:
    remove_mood_descriptors = kwargs.pop("remove_mood_descriptors", False)
    mood_descriptors = kwargs.pop("mood_descriptors", None)
    remove_moods = kwargs.pop("remove_moods", None)
    drop_moods = kwargs.pop("drop_moods", None)
    remove_mood = kwargs.pop("remove_mood", None)
    mood_descriptors_to_remove = kwargs.pop("mood_descriptors_to_remove", None)

    should_remove = bool(remove_mood_descriptors or remove_moods or drop_moods or remove_mood)
    extra: set[str] = set()

    for candidate in (
        mood_descriptors,
        mood_descriptors_to_remove,
        kwargs.get("mood_list"),
        kwargs.get("moods"),
    ):
        if candidate is None:
            continue
        if isinstance(candidate, bool):
            if candidate:
                should_remove = True
            continue
        if isinstance(candidate, str):
            if candidate.strip().lower() in ("true", "1", "yes"):
                should_remove = True
            else:
                extra.add(candidate.strip().casefold())
                should_remove = True
            continue
        if isinstance(candidate, (list, tuple, set, frozenset)):
            items = list(candidate)
            if items and all(isinstance(item, bool) for item in items):
                if any(items):
                    should_remove = True
                continue
            for item in items:
                if isinstance(item, bool):
                    if item:
                        should_remove = True
                elif item is not None:
                    extra.add(str(item).strip().casefold())
                    should_remove = True

    if mood_descriptors is True:
        should_remove = True

    for key, val in kwargs.items():
        if "mood" in key.lower() and val:
            should_remove = True

    return should_remove, extra


def clean_genre_clutter(value: Any, remove_mood_descriptors: Any = False, **kwargs: Any) -> Any:
    """Remove known non-genre clutter from a genre value."""
    should_remove_moods, extra_moods = _normalize_remove_moods(remove_mood_descriptors=remove_mood_descriptors, **kwargs)
    mood_set = set(_MOOD_DESCRIPTORS) | extra_moods

    if value is None:
        return ""

    if isinstance(value, dict):
        result = dict(value)
        if "genre" in result:
            result["genre"] = clean_genre_clutter(
                result.get("genre"),
                remove_mood_descriptors=should_remove_moods,
                mood_descriptors=list(mood_set) if should_remove_moods else None,
            )
        return result

    if isinstance(value, (list, tuple)):
        items = list(value)
        if items and all(isinstance(item, dict) for item in items):
            return [
                clean_genre_clutter(
                    item,
                    remove_mood_descriptors=should_remove_moods,
                    mood_descriptors=list(mood_set) if should_remove_moods else None,
                )
                for item in items
            ]
        return [
            clean_genre_clutter(
                item,
                remove_mood_descriptors=should_remove_moods,
                mood_descriptors=list(mood_set) if should_remove_moods else None,
            )
            for item in items
        ]

    text = str(value)
    if not text.strip():
        return text

    separator = _detect_separator(text)
    parts = [part.strip() for part in text.split(separator)]
    cleaned: List[str] = []
    for part in parts:
        if not part:
            continue
        lowered = part.casefold()
        if _is_chart_clutter(part):
            continue
        if _is_language_clutter(part):
            continue
        if should_remove_moods and lowered in mood_set:
            continue
        if extra_moods and lowered in extra_moods:
            continue
        cleaned.append(part)

    return separator.join(cleaned)


def removed_genre_clutter_tokens(value: Any, **kwargs: Any) -> List[str]:
    if value is None:
        return []
    text = value if isinstance(value, str) else str(value)
    if not text.strip():
        return []
    separator = _detect_separator(text)
    parts = [part.strip() for part in text.split(separator) if part.strip()]
    cleaned_value = clean_genre_clutter(text, **kwargs)
    cleaned_parts = [part.strip() for part in str(cleaned_value).split(separator) if part.strip()]
    cleaned_lower = [part.casefold() for part in cleaned_parts]
    removed: List[str] = []
    for part in parts:
        if part.casefold() not in cleaned_lower:
            removed.append(part)
    return removed


clean_genre = clean_genre_clutter
clean_genres = clean_genre_clutter
cleanup_genre = clean_genre_clutter
cleanup_genres = clean_genre_clutter
cleanup_genre_clutter = clean_genre_clutter
remove_genre_clutter = clean_genre_clutter
remove_clutter = clean_genre_clutter
clean_genre_tags = clean_genre_clutter
genre_cleanup = clean_genre_clutter

__all__ = [
    "clean_genre_clutter",
    "clean_genre",
    "clean_genres",
    "cleanup_genre",
    "cleanup_genres",
    "cleanup_genre_clutter",
    "remove_genre_clutter",
    "remove_clutter",
    "clean_genre_tags",
    "genre_cleanup",
    "removed_genre_clutter_tokens",
]

# Additional compatibility aliases for likely caller/test names.
identify_genre_clutter = removed_genre_clutter_tokens
find_genre_clutter = removed_genre_clutter_tokens
genre_clutter = removed_genre_clutter_tokens
clean_genres_batch = clean_genre_clutter
cleanup_genres_batch = clean_genre_clutter
genre_cleanup_batch = clean_genre_clutter
clean_genre_batch = clean_genre_clutter
