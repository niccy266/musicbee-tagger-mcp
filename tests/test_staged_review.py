"""Terminal display tests for staged tag reviews."""

from wcwidth import wcswidth

from musicbee_tagger_mcp.staged_review import _display_value, _print_diff, print_review


def test_display_value_escapes_terminal_controls():
    assert _display_value("title\x1b[31m\n\u202e") == (
        "title\\u001b[31m\\u000a\\u202e"
    )


def test_print_diff_wraps_long_values_within_table(capsys):
    _print_diff(
        [{
            "field": "album",
            "old": "A very long album title that should wrap across lines",
            "new": "Another long album title that should wrap across lines",
        }],
        original_title="Song",
        proposed_title="Song",
    )
    lines = capsys.readouterr().out.splitlines()
    album_line = next(i for i, line in enumerate(lines) if "| album" in line)
    assert "should wrap across" in lines[album_line + 1]
    assert {wcswidth(line) for line in lines} == {80}


def test_print_diff_aligns_wide_metadata(capsys):
    _print_diff(
        [{"field": "album", "old": "雪の女王", "new": "千と千尋の神隠し"}],
        original_title="千と千尋",
        proposed_title="千と千尋",
    )
    widths = {wcswidth(line) for line in capsys.readouterr().out.splitlines()}
    assert widths == {80}


def test_print_review_always_shows_primary_fields_and_marks_unchanged(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        "musicbee_tagger_mcp.staged_review.read_audio_metadata",
        lambda _: {"tags": {"artist": "Old Artist", "title": "Song", "album": "Album"}},
    )
    manifest = {
        "absolute_path": "track.mp3",
        "display_name": "track.mp3",
        "proposed_tags": {"artist": "New Artist"},
        "diff": [{"field": "artist", "old": "Old Artist", "new": "New Artist"}],
    }

    print_review(manifest, "stage-id")

    output = capsys.readouterr().out
    artist_row = output.index("| artist")
    title_row = output.index("| title")
    album_row = output.index("| album")
    assert artist_row < title_row < album_row
    assert "New Artist" in output[artist_row:title_row]
    assert "(no change)" in output[title_row:album_row]
    assert "(no change)" in output[album_row:]
