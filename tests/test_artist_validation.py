"""Tests for MusicBrainz-backed artist split validation."""

from musicbee_tagger_mcp.artist_validation import (
    heuristic_flags,
    propose_split,
)


def test_propose_split_finds_featured():
    result = propose_split("Kendrick Lamar feat. Lil Nas X")
    assert result["changed"]
    assert result["candidates"] == ["Kendrick Lamar", "Lil Nas X"]
    assert "feat" in result["joiners_found"]


def test_propose_split_clean_name_unchanged():
    result = propose_split("Kendrick Lamar")
    assert not result["changed"]
    assert result["candidates"] == ["Kendrick Lamar"]


def test_flags_short_and_mojibake():
    flags = heuristic_flags(["Xy", "Ãœnknown Ãrtist"])
    artists = [f["artist"] for f in flags]
    assert "Xy" in artists
    assert any("mojibake" in f["flags"] for f in flags)


def test_flags_clean_artists():
    assert heuristic_flags(["Kendrick Lamar", "Lil Nas X"]) == []
