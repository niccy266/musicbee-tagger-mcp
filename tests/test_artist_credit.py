"""Tests for artist_credit helpers."""

from musicbee_tagger_mcp.artist_credit import (
    artist_tag_value,
    credit_names,
    normalize_artist_value,
)


def test_credit_names_extracts_deduplicated():
    credit = [
        {"artist": {"name": "A"}},
        {"artist": {"name": "B"}},
        {"artist": {"name": "A"}},
        " & ",
        {"artist": {"name": "C"}},
    ]
    assert credit_names(credit) == ["A", "B", "C"]


def test_credit_names_handles_empty():
    assert credit_names(None) == []
    assert credit_names([]) == []
    assert credit_names(" & ") == []


def test_artist_tag_value_joins_with_semicolon():
    assert artist_tag_value(["A", "B"]) == "A; B"
    assert artist_tag_value(["Solo"]) == "Solo"
    assert artist_tag_value([]) == ""


def test_normalize_artist_value_preserves_single_act():
    value, warnings = normalize_artist_value("Earth, Wind & Fire", ["Earth, Wind & Fire"])
    assert value == "Earth, Wind & Fire"
    assert warnings == []


def test_normalize_artist_value_uses_credited_names():
    value, warnings = normalize_artist_value(
        "David Bowie; Queen", ["David Bowie", "Queen"]
    )
    assert value == "David Bowie; Queen"
    assert warnings == []


def test_normalize_artist_value_warns_on_unsplit_joiner():
    value, warnings = normalize_artist_value("Foo & Bar", None)
    assert " & " in value
    assert any("confirm whether this is one act or several" in w for w in warnings)


def test_normalize_artist_value_warns_semicolon_in_credited_name():
    value, warnings = normalize_artist_value(
        "Earth, Wind & Fire", ["Earth, Wind & Fire"]
    )
    assert value == "Earth, Wind & Fire"
    assert warnings == []


def test_normalize_artist_value_handles_non_string():
    value, warnings = normalize_artist_value(None, None)
    assert value is None
    assert warnings == []


def test_normalize_artist_value_strips_whitespace():
    value, warnings = normalize_artist_value("  Foo ; Bar  ", ["Foo", "Bar"])
    assert value == "Foo; Bar"
    assert warnings == []