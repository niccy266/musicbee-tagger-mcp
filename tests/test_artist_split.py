"""Tests for artist field splitting."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from musicbee_tagger_mcp.artist_split import (
    join_artists,
    needs_split,
    split_artists,
)


def test_featured_marker():
    assert split_artists("Kendrick Lamar feat. Lil Nas X") == [
        "Kendrick Lamar", "Lil Nas X"]


def test_ft_and_featuring():
    assert split_artists("A ft. B") == ["A", "B"]
    assert split_artists("A featuring B") == ["A", "B"]
    assert split_artists("A feat B") == ["A", "B"]


def test_case_insensitive():
    assert split_artists("A FEAT. B") == ["A", "B"]


def test_with_and_vs():
    assert split_artists("Taylor Swift with Bon Iver") == [
        "Taylor Swift", "Bon Iver"]
    assert split_artists("A vs. B") == ["A", "B"]


def test_lone_x_marker():
    assert split_artists("Dua Lipa x DaBaby") == ["Dua Lipa", "DaBaby"]


def test_x_inside_names_preserved():
    assert split_artists("Lil Nas X") == ["Lil Nas X"]
    assert split_artists("DJ X") == ["DJ X"]
    assert split_artists("Lil Nas X feat. Billy Ray Cyrus") == [
        "Lil Nas X", "Billy Ray Cyrus"]


def test_existing_semicolons_are_boundaries():
    assert split_artists("A; B") == ["A", "B"]
    assert split_artists("A ;B;C ") == ["A", "B", "C"]


def test_ampersand_opt_in():
    assert split_artists("A & B") == ["A & B"]
    assert split_artists("A & B", split_ampersand=True) == ["A", "B"]


def test_band_names_survive():
    assert split_artists("Mumford & Sons") == ["Mumford & Sons"]
    assert split_artists("Earth, Wind & Fire") == ["Earth, Wind & Fire"]


def test_comma_opt_in():
    assert split_artists("A, B") == ["A, B"]
    assert split_artists("A, B", split_comma=True) == ["A", "B"]


def test_empty_and_noop():
    assert split_artists("") == []
    assert split_artists("   ") == []
    assert split_artists("Just One Artist") == ["Just One Artist"]


def test_dedupe_preserves_order():
    assert split_artists("A feat. A feat. B") == ["A", "B"]


def test_dedupe_case_insensitive():
    assert split_artists("A feat. a") == ["A"]


def test_join_roundtrip():
    assert join_artists(["Kendrick Lamar", "Lil Nas X"]) == (
        "Kendrick Lamar; Lil Nas X")


def test_needs_split():
    assert needs_split("Kendrick Lamar feat. Lil Nas X")
    assert not needs_split("Mumford & Sons")
    assert not needs_split("Kendrick Lamar")
