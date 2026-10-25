"""Configured MusicBrainz API client shared by search and verification."""

import musicbrainzngs

musicbrainzngs.set_useragent(
    "musicbee-tagger-mcp",
    "0.4.4",
    "https://github.com/niccy266/musicbee-tagger-mcp",
)
