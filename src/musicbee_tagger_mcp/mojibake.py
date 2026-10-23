"""Mojibake and character encoding detection and repair utilities."""

from typing import Dict, Any, Optional
import ftfy

COMMON_ENCODING_PAIRS = [
    ("latin1", "cp1251"),   # Cyrillic Windows-1251 misinterpreted as Western Latin-1
    ("cp1252", "cp1251"),   # Cyrillic Windows-1251 misinterpreted as CP1252
    ("latin1", "cp932"),    # Japanese Shift-JIS misinterpreted as Latin-1
    ("cp1252", "cp932"),    # Japanese Shift-JIS misinterpreted as CP1252
    ("latin1", "utf-8"),    # Double-encoded UTF-8
    ("cp1252", "utf-8"),
]

def contains_cyrillic(text: str) -> bool:
    """Check if text contains Cyrillic characters."""
    return any("\u0400" <= char <= "\u04FF" for char in text)

def contains_cjk(text: str) -> bool:
    """Check if text contains Japanese/Chinese/Korean characters."""
    return any(
        ("\u3040" <= char <= "\u309F") or  # Hiragana
        ("\u30A0" <= char <= "\u30FF") or  # Katakana
        ("\u4E00" <= char <= "\u9FFF")     # Kanji / Hanzi
        for char in text
    )

def fix_mojibake(text: str) -> Dict[str, Any]:
    """
    Attempt to detect and fix mojibake in text.
    Returns a dict with original, repaired, was_repaired, and explanation.
    """
    if not text or not isinstance(text, str):
        return {
            "original": text,
            "repaired": text,
            "was_repaired": False,
            "strategy": "none"
        }

    # 1. First, check if ftfy can resolve it directly
    ftfy_fixed = ftfy.fix_text(text)
    if ftfy_fixed != text:
        return {
            "original": text,
            "repaired": ftfy_fixed,
            "was_repaired": True,
            "strategy": "ftfy_auto"
        }

    # 2. Try known encoding re-interpretations
    for bad_enc, real_enc in COMMON_ENCODING_PAIRS:
        try:
            # Re-encode as the 'bad' encoding bytes and decode as the 'real' encoding
            re_encoded = text.encode(bad_enc)
            decoded = re_encoded.decode(real_enc)
            
            # Check if decoding produced meaningful characters (Cyrillic or CJK)
            # and doesn't look like more gibberish
            if (real_enc == "cp1251" and contains_cyrillic(decoded)) or \
               (real_enc == "cp932" and contains_cjk(decoded)):
                return {
                    "original": text,
                    "repaired": decoded,
                    "was_repaired": True,
                    "strategy": f"{bad_enc}_to_{real_enc}"
                }
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue

    return {
        "original": text,
        "repaired": text,
        "was_repaired": False,
        "strategy": "none"
    }

def normalize_russian_yo(text: str, to_e: bool = False) -> str:
    """
    Normalize Russian 'Ё' / 'ё' to 'Е' / 'е' (or keep note of difference).
    Useful for cross-referencing databases that lack 'ё' standardization.
    """
    if to_e:
        return text.replace("ё", "е").replace("Ё", "Е")
    return text
