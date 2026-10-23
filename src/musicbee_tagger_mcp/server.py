"""MusicBee Tagger MCP Server entry point."""

from typing import Dict, Any, Optional, List
import json
from mcp.server.mcpserver import MCPServer
from .metadata_reader import read_audio_metadata
from .mojibake import fix_mojibake, normalize_russian_yo
from .musicbrainz_client import search_recordings_forensic
from .tag_writer import preview_tag_changes, apply_tags_to_file

# Initialize MCP Server
app = MCPServer("musicbee-tagger")

@app.tool()
def read_track_metadata(file_path: str) -> Dict[str, Any]:
    """
    Read metadata and audio stream specs (duration, bitrate, format) from a local audio file.
    Supports MP3, FLAC, OGG, M4A, etc.
    """
    return read_audio_metadata(file_path)

@app.tool()
def repair_mojibake(text: str) -> Dict[str, Any]:
    """
    Detect and repair corrupted character encoding (Mojibake).
    Specialized for Soviet/Russian Cyrillic (Windows-1251 misread as Latin-1)
    and Japanese Shift-JIS/CP932.
    """
    return fix_mojibake(text)

@app.tool()
def search_canonical_release(
    artist: str,
    title: str,
    duration_sec: Optional[float] = None,
    clue: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Search MusicBrainz for matching recordings and rank releases forensically.
    Uses track duration matching (±2.5s for exact match) and context clues (venues, years, subtitles)
    to classify releases into Studio Album, Live Release, Single/EP, or Compilation.
    """
    return search_recordings_forensic(
        artist=artist,
        title=title,
        duration_sec=duration_sec,
        clue=clue,
        limit=limit
    )

@app.tool()
def preview_tags(file_path: str, new_tags: Dict[str, Any]) -> Dict[str, Any]:
    """
    Preview the field-by-field diff of proposed tag changes against the file's current metadata
    without writing anything to disk.
    Supported keys: title, artist, album, album_artist, track_number, year, original_year, musicbrainz_track_id, musicbrainz_release_id.
    """
    return preview_tag_changes(file_path, new_tags)

@app.tool()
def apply_tags(
    file_path: str,
    new_tags: Dict[str, Any],
    create_backup: bool = True
) -> Dict[str, Any]:
    """
    Safely commit clean UTF-8 tags to the audio file on disk.
    Automatically creates a .bak backup file before modifying, unless create_backup=False.
    """
    return apply_tags_to_file(file_path, new_tags, create_backup=create_backup)

def main():
    """Main entrypoint for MCP stdio transport."""
    app.run(transport="stdio")

if __name__ == "__main__":
    main()
