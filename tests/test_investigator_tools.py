"""Unit tests for filename parser and MBID verification gate."""

import pytest
from unittest.mock import patch

from musicbee_tagger_mcp.filename_parser import extract_clues_from_filename, clean_stem
from musicbee_tagger_mcp.musicbrainz_client import classify_release, verify_recording_mbid, string_similarity


def test_filename_clean_stem():
    assert clean_stem("01 - Test Track.mp3") == "01 - Test Track"
    assert clean_stem("Song Name_1.ogg") == "Song Name"
    assert clean_stem("Album [FLAC].flac") == "Album [FLAC]"


def test_filename_parser_standard():
    res = extract_clues_from_filename("01 - Jimmy Takeuchi - Drum Drum Drum (1970).mp3")
    assert res["track_number_guess"] == 1
    assert res["artist_guess"] is None
    assert res["title_guess"] is None
    assert res["artist_title_candidates"] == [
        {"artist": "Jimmy Takeuchi", "title": "Drum Drum Drum"},
        {"artist": "Drum Drum Drum", "title": "Jimmy Takeuchi"},
    ]
    assert res["year_guess"] == "1970"


def test_filename_parser_regional_brackets():
    res = extract_clues_from_filename("ちゃっきり節 (静岡) - ジミー竹内.ogg")
    assert "静岡" in res["bracket_clues"]
    assert res["artist_title_candidates"] == [
        {"artist": "ちゃっきり節", "title": "ジミー竹内"},
        {"artist": "ジミー竹内", "title": "ちゃっきり節"},
    ]


def test_filename_parser_does_not_assume_sample_order():
    res = extract_clues_from_filename(
        "The Knack (Main Theme) - John Barry And His Orchestra_1.ogg"
    )
    assert res["artist_guess"] is None
    assert res["title_guess"] is None
    assert res["artist_title_candidates"] == [
        {"artist": "The Knack", "title": "John Barry And His Orchestra"},
        {"artist": "John Barry And His Orchestra", "title": "The Knack"},
    ]
    assert res["bracket_clues"] == ["Main Theme"]


def test_string_similarity():
    assert string_similarity("The Knack", "The Knack") == 1.0
    assert string_similarity("The Knack (Main Theme)", "The Knack") > 0.6
    assert string_similarity("Different", "Completely") < 0.3


def test_classify_release_without_type_metadata():
    assert classify_release({"title": "Great Movie Sounds of John Barry"})["category"] == "Unknown"


def test_verify_mbid_mocked_success():
    mock_mb_data = {
        "recording": {
            "title": "The Knack (Main Theme)",
            "artist-credit-phrase": "John Barry and His Orchestra",
            "length": 175000,  # 175.0s
            "release-list": [
                {
                    "id": "rel-uuid-1",
                    "title": "The Knack ...and How to Get It",
                    "date": "1965",
                    "country": "GB",
                    "release-group": {
                        "primary-type": "Album",
                        "secondary-type-list": [],
                    },
                }
            ],
        }
    }

    with patch("musicbrainzngs.get_recording_by_id", return_value=mock_mb_data) as get_recording:
        res = verify_recording_mbid(
            recording_id="rec-uuid-123",
            expected_artist="John Barry And His Orchestra",
            expected_title="The Knack (Main Theme)",
            duration_sec=174.68,
        )

        assert res["verified"] is True
        assert res["confidence"] >= 85.0
        assert res["duration_diff_seconds"] <= 0.5
        assert res["top_release"]["album_title"] == "The Knack ...and How to Get It"
        assert len(res["mismatches"]) == 0
        get_recording.assert_called_once_with(
            "rec-uuid-123",
            includes=["artists", "releases"],
        )


def test_verify_mbid_mocked_mismatch():
    mock_mb_data = {
        "recording": {
            "title": "Completely Different Song",
            "artist-credit-phrase": "Someone Else",
            "length": 300000,  # 300s vs 174s
            "release-list": [],
        }
    }

    with patch("musicbrainzngs.get_recording_by_id", return_value=mock_mb_data):
        res = verify_recording_mbid(
            recording_id="rec-uuid-999",
            expected_artist="John Barry",
            expected_title="The Knack",
            duration_sec=174.0,
        )

        assert res["verified"] is False
        assert res["confidence"] < 60.0
        assert len(res["mismatches"]) >= 2
