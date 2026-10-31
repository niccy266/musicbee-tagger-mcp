"""Unit tests for filename parser and MBID verification gate."""

import pytest
from unittest.mock import patch

from musicbee_tagger_mcp.filename_parser import extract_clues_from_filename, clean_stem
from musicbee_tagger_mcp.musicbrainz_client import classify_release, evaluate_match, string_similarity


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
        {"artist": "Jimmy Takeuchi", "title": "Drum Drum Drum (1970)"},
        {"artist": "Drum Drum Drum (1970)", "title": "Jimmy Takeuchi"},
    ]
    assert res["artist_title_candidates_are_unverified"] is True
    assert "unverified" in res["artist_title_candidates_note"].lower()
    assert res["year_guess"] == "1970"


def test_filename_parser_regional_brackets():
    res = extract_clues_from_filename("ちゃっきり節 (静岡) - ジミー竹内.ogg")
    assert "静岡" in res["bracket_clues"]
    assert res["artist_title_candidates"] == [
        {"artist": "ちゃっきり節 (静岡)", "title": "ジミー竹内"},
        {"artist": "ジミー竹内", "title": "ちゃっきり節 (静岡)"},
    ]


def test_filename_parser_does_not_assume_sample_order():
    res = extract_clues_from_filename(
        "The Knack (Main Theme) - John Barry And His Orchestra_1.ogg"
    )
    assert res["artist_guess"] is None
    assert res["title_guess"] is None
    assert res["artist_title_candidates"] == [
        {"artist": "The Knack (Main Theme)", "title": "John Barry And His Orchestra"},
        {"artist": "John Barry And His Orchestra", "title": "The Knack (Main Theme)"},
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
        res = evaluate_match(
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
            includes=["artists", "releases", "tags"],
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
        res = evaluate_match(
            recording_id="rec-uuid-999",
            expected_artist="John Barry",
            expected_title="The Knack",
            duration_sec=174.0,
        )

        assert res["verified"] is False
        assert res["confidence"] < 60.0
        assert len(res["mismatches"]) >= 2


def test_filename_clean_stem_preserves_meaningful_suffix():
    assert clean_stem("Song_2020.mp3") == "Song_2020"
    assert clean_stem("Song Name_1.ogg") == "Song Name"
    assert clean_stem("Track_02.flac") == "Track"


def test_filename_clean_stem_sanitizes_invisible_chars():
    assert clean_stem("Song\u200e Name.mp3") == "Song Name"


def test_filename_parser_does_not_treat_hyphenated_title_as_track_number():
    res = extract_clues_from_filename("99-Luftballons.mp3")
    assert res["track_number_guess"] is None
    assert res["title_guess"] == "99-Luftballons"
    res2 = extract_clues_from_filename("7-Seconds.mp3")
    assert res2["track_number_guess"] is None
    assert res2["title_guess"] == "7-Seconds"


def test_filename_parser_preserves_bracketed_title_text():
    res = extract_clues_from_filename("Artist - Title (Live).mp3")
    assert res["artist_title_candidates"] == [
        {"artist": "Artist", "title": "Title (Live)"},
        {"artist": "Title (Live)", "title": "Artist"},
    ]
    assert "Live" in res["bracket_clues"]


def test_filename_parser_nested_brackets():
    res = extract_clues_from_filename("Artist - Title (Live (Acoustic)).mp3")
    assert res["artist_title_candidates"][0]["title"] == "Title (Live (Acoustic))"
    assert res["bracket_clues"] == ["Live (Acoustic)"]


def test_filename_parser_sanitizes_invisible_chars():
    res = extract_clues_from_filename("Art\u200eist - Tit\u200ele.mp3")
    assert res["artist_title_candidates"] == [
        {"artist": "Artist", "title": "Title"},
        {"artist": "Title", "title": "Artist"},
    ]
    assert "\u200e" not in res["cleaned_stem"]


def test_filename_parser_three_or_more_segments():
    res = extract_clues_from_filename("Artist - Title - Subtitle - Extra.mp3")
    assert res["artist_title_candidates"] == [
        {"artist": "Artist", "title": "Title - Subtitle - Extra"},
        {"artist": "Title - Subtitle - Extra", "title": "Artist"},
    ]


def test_filename_parser_multilingual_examples():
    res = extract_clues_from_filename("Bj\u00f6rk - J\u00f3ga (Live).mp3")
    assert res["artist_title_candidates"][0]["artist"] == "Bj\u00f6rk"
    assert "Live" in res["bracket_clues"]
    res2 = extract_clues_from_filename("\u3061\u3083\u3063\u304d\u308a\u7bc0 (\u9759\u5ca1) - \u30b8\u30df\u30fc\u7af9\u5185.ogg")
    assert "\u9759\u5ca1" in res2["bracket_clues"]
