"""Unit tests for musicbee-tagger-mcp."""

import pytest
from musicbee_tagger_mcp.mojibake import fix_mojibake, contains_cyrillic, contains_cjk
from musicbee_tagger_mcp.musicbrainz_client import calculate_duration_score, classify_release
from musicbee_tagger_mcp.tag_writer import preview_tag_changes

def test_mojibake_cyrillic_repair():
    # 'Нас звёзды ждут' encoded as cp1251 and wrongly decoded as latin1
    corrupted = "Íàñ çâ¸çäû æäóò"
    res = fix_mojibake(corrupted)
    assert res["was_repaired"] is True
    assert res["repaired"] == "Нас звёзды ждут"

def test_mojibake_clean_text_intact():
    clean_text = "Pink Floyd - Comfortably Numb"
    res = fix_mojibake(clean_text)
    assert res["was_repaired"] is False
    assert res["repaired"] == clean_text

def test_contains_charsets():
    assert contains_cyrillic("Кино") is True
    assert contains_cyrillic("Queen") is False
    assert contains_cjk("ちゃっきり節 (静岡)") is True
    assert contains_cjk("The Beatles") is False

def test_duration_scoring():
    # Exact match (within 2.5s)
    score, note = calculate_duration_score(240.0, 241000)
    assert score == 30.0
    assert "exact_match" in note

    # Significant mismatch (> 15s)
    score, note = calculate_duration_score(240.0, 310000)
    assert score == -25.0
    assert "duration_mismatch" in note

def test_classify_release():
    rel_live = {
        "title": "Live at Pompeii",
        "release-group": {
            "primary-type": "Album",
            "secondary-type-list": ["Live"]
        }
    }
    res = classify_release(rel_live)
    assert res["category"] == "Live Release"
    assert res["is_live"] is True

    rel_studio = {
        "title": "Dark Side of the Moon",
        "release-group": {
            "primary-type": "Album",
            "secondary-type-list": []
        }
    }
    res = classify_release(rel_studio)
    assert res["category"] == "Studio Album"
    assert res["is_live"] is False
