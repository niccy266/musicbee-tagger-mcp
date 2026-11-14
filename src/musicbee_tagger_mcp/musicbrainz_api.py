"""Configured MusicBrainz API client shared by search and verification."""

import musicbrainzngs

musicbrainzngs.set_useragent(
    "musicbee-tagger-mcp",
    "0.4.6",
    "niccy266@gmail.com",
)
