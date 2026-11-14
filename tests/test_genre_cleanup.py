"""Unit and integration tests for genre clutter cleanup helpers and MCP tool."""

import json
import pytest

from musicbee_tagger_mcp.file_registry import FileRegistry
from musicbee_tagger_mcp.genre_cleanup import (
    clean_genre_clutter,
    removed_genre_clutter_tokens,
    _detect_separator,
    _is_chart_clutter,
    _is_language_clutter,
)
from musicbee_tagger_mcp.tools import genre_cleanup as tool_genre_cleanup


def test_detect_separator():
    assert _detect_separator("Rock; Pop") == "; "
    assert _detect_separator("Rock;Pop") == ";"
    assert _detect_separator("Rock, Pop") == ", "
    assert _detect_separator("Rock,Pop") == ","
    assert _detect_separator("Rock|Pop") == "|"
    assert _detect_separator("Rock\nPop") == "\n"
    assert _detect_separator("Rock\tPop") == "\t"
    assert _detect_separator("Rock") == "; "


def test_chart_clutter_detection():
    assert _is_chart_clutter("Top 100") is True
    assert _is_chart_clutter("Official Charts") is True
    assert _is_chart_clutter("10 Wochen") is True
    assert _is_chart_clutter("1 - 2 wochen") is True
    assert _is_chart_clutter("5 weeks") is True
    assert _is_chart_clutter("1 week") is True
    assert _is_chart_clutter("Pop") is False
    assert _is_chart_clutter("Classic Rock") is False


def test_language_clutter_detection():
    assert _is_language_clutter("English") is True
    assert _is_language_clutter("german") is True
    assert _is_language_clutter("Japanese") is True
    assert _is_language_clutter("J-Pop") is False
    assert _is_language_clutter("K-Pop") is False


def test_clean_genre_clutter_basic():
    # Empty and None handling
    assert clean_genre_clutter(None) == ""
    assert clean_genre_clutter("") == ""
    assert clean_genre_clutter("   ") == "   "

    # Preserves legitimate genres while stripping chart and language clutter
    raw = "Rock; Top 100; German; 10 Wochen; Alternative"
    cleaned = clean_genre_clutter(raw)
    assert cleaned == "Rock; Alternative"

    # Different separators
    raw_comma = "Electronic, English, Ambient, 3 weeks"
    assert clean_genre_clutter(raw_comma) == "Electronic, Ambient"

    raw_pipe = "Metal|French|Heavy Metal"
    assert clean_genre_clutter(raw_pipe) == "Metal|Heavy Metal"


def test_clean_genre_clutter_moods():
    raw = "Indie; Melancholic; Sad; Chill; Post-Punk"
    
    # By default, moods are preserved
    assert clean_genre_clutter(raw, remove_mood_descriptors=False) == raw

    # When remove_mood_descriptors=True
    cleaned = clean_genre_clutter(raw, remove_mood_descriptors=True)
    assert cleaned == "Indie; Post-Punk"

    # Alternate kwargs: remove_moods, drop_moods, extra custom mood descriptors
    cleaned_custom = clean_genre_clutter(
        "Indie; Gloomy; CustomMood; Post-Punk",
        remove_moods=True,
        mood_descriptors=["CustomMood"],
    )
    assert cleaned_custom == "Indie; Post-Punk"

    # Boolean and string variations for mood descriptor arguments
    cleaned_str = clean_genre_clutter("Rock; Happy", mood_descriptors="true")
    assert cleaned_str == "Rock"


def test_clean_genre_clutter_nested_structures():
    # Dictionary with "genre" key
    data = {"artist": "Radiohead", "genre": "Alternative; Top 40; Art Rock"}
    cleaned_data = clean_genre_clutter(data)
    assert cleaned_data["artist"] == "Radiohead"
    assert cleaned_data["genre"] == "Alternative; Art Rock"

    # List of strings
    items = ["Pop; English", "Rock; 10 Wochen; Grunge"]
    cleaned_items = clean_genre_clutter(items)
    assert cleaned_items == ["Pop", "Rock; Grunge"]

    # List of dictionaries
    dict_items = [{"genre": "Jazz; French"}, {"genre": "Blues; Charts"}]
    cleaned_dicts = clean_genre_clutter(dict_items)
    assert cleaned_dicts[0]["genre"] == "Jazz"
    assert cleaned_dicts[1]["genre"] == "Blues"


def test_removed_genre_clutter_tokens():
    assert removed_genre_clutter_tokens(None) == []
    assert removed_genre_clutter_tokens("") == []
    
    raw = "Rock; Top 100; English; Alternative"
    removed = removed_genre_clutter_tokens(raw)
    assert "Top 100" in removed
    assert "English" in removed
    assert "Rock" not in removed
    assert "Alternative" not in removed


def test_tool_clean_genre_clutter(tmp_path, monkeypatch):
    reg = FileRegistry(directory=tmp_path / "reg")
    reg.directory.mkdir()

    # Track 1: needs cleanup
    file1 = tmp_path / "song1.mp3"
    file1.write_bytes(b"\x00" * 16)
    token1 = reg.register(str(file1))["token"]

    # Track 2: clean, no changes needed
    file2 = tmp_path / "song2.mp3"
    file2.write_bytes(b"\x00" * 16)
    token2 = reg.register(str(file2))["token"]

    # Track 3: unreadable
    file3 = tmp_path / "song3.mp3"
    file3.write_bytes(b"\x00" * 16)
    token3 = reg.register(str(file3))["token"]

    def fake_read(path):
        if "song1" in path:
            return {"tags": {"genre": "Rock; Top 100; English"}}
        if "song2" in path:
            return {"tags": {"genre": "Progressive Rock"}}
        raise RuntimeError("Corrupt file")

    monkeypatch.setattr(tool_genre_cleanup, "get_registry", lambda: reg)
    monkeypatch.setattr(tool_genre_cleanup, "read_audio_metadata", fake_read)

    unknown_token = "00000000-0000-0000-0000-000000000000"
    result = tool_genre_cleanup.clean_genre_clutter([token1, token2, token3, unknown_token])

    assert result["total"] == 4
    assert result["changed_count"] == 1
    assert result["skipped_count"] == 1

    # Check changed track 1
    changed = result["changed_tracks"][0]
    assert changed["token"] == token1
    assert changed["genre_after"] == "Rock"
    assert "Top 100" in changed["removed"]
    assert "English" in changed["removed"]
    assert changed["changed"] is True

    # Check skipped track 2
    assert token2 in result["skipped"]

    # Check errors
    error_tokens = [e.get("token") for e in result["errors"]]
    assert token3 in error_tokens
    assert unknown_token in error_tokens

    # Verify path leak hardening
    assert str(tmp_path) not in json.dumps(result)
