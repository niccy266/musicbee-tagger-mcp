"""MusicBrainz genre tags remain attached to their matching recording."""

from musicbee_tagger_mcp import musicbrainz_search
from musicbee_tagger_mcp import musicbrainz_verification


def test_search_returns_deduplicated_recording_and_release_genres(monkeypatch):
    monkeypatch.setattr(
        musicbrainz_search.musicbrainzngs,
        "search_recordings",
        lambda **kwargs: {"recording-list": [{
            "id": "recording-1",
            "title": "Song",
            "artist-credit-phrase": "Artist",
            "length": "180000",
            "tag-list": [{"name": "Rock"}, {"name": "Alternative"}],
            "release-list": [{
                "id": "release-1", "title": "Album",
                "tag-list": [{"name": "Rock"}, {"name": "Indie"}],
            }],
        }]},
    )

    result = musicbrainz_search.search_recordings_forensic("Artist", "Song")

    assert result[0]["recording_id"] == "recording-1"
    assert result[0]["genre"] == "Rock; Alternative; Indie"


def test_verification_returns_recording_and_release_genres(monkeypatch):
    monkeypatch.setattr(
        musicbrainz_verification.musicbrainzngs,
        "get_recording_by_id",
        lambda *args, **kwargs: {"recording": {
            "id": "recording-1", "title": "Song",
            "artist-credit-phrase": "Artist", "length": "180000",
            "tag-list": [{"name": "Rock"}],
            "release-list": [{"id": "release-1", "title": "Album",
                              "tag-list": [{"name": "Indie"}]}],
        }},
    )

    result = musicbrainz_verification.verify_recording_mbid("recording-1")

    assert result["genre"] == "Rock; Indie"
