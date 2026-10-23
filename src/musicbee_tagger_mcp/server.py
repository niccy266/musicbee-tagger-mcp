"""MusicBee Tagger MCP Server — secure token-based pipeline.

Security properties:
- File paths are consumed at registration and replaced with opaque UUID tokens.
- No tool ever returns a file path to the agent or user.
- Tag writes are NOT available as MCP tools. The agent can only STAGE changes.
- Staged changes are applied exclusively via the user-facing CLI:
      python -m musicbee_tagger_mcp.apply_staged
"""

from typing import Dict, Any, Optional, List
from mcp.server.mcpserver import MCPServer

from .file_registry import get_registry
from .staging import get_staging_manager
from .metadata_reader import read_audio_metadata
from .mojibake import fix_mojibake
from .musicbrainz_client import search_recordings_forensic, verify_recording_mbid
from .tag_writer import preview_tag_changes
from .filename_parser import extract_clues_from_filename
from .playlist import parse_m3u_playlist

app = MCPServer("musicbee-tagger")


# ---------------------------------------------------------------------------
# Tool 1: File registration — paths go in, tokens come out
# ---------------------------------------------------------------------------

@app.tool()
def register_files(paths: List[str]) -> List[Dict[str, str]]:
    """
    Register one or more local audio file paths for analysis in this session.

    Paths are stored internally and replaced with opaque UUID tokens.
    Tokens (not paths) are used for all subsequent tool calls.

    Returns a list of {"token": str, "display_name": str} — display_name is
    the bare filename only (no directory, no path).
    """
    registry = get_registry()
    results = []
    for path in paths:
        try:
            results.append(registry.register(path))
        except FileNotFoundError:
            results.append({"error": "File not found"})
        except OSError:
            results.append({"error": "Unable to access file"})
        except (RuntimeError, ValueError):
            results.append({"error": "Unable to resolve file"})
    return results


# ---------------------------------------------------------------------------
# Tool 2: Playlist registration — resolve paths privately, return tokens
# ---------------------------------------------------------------------------

@app.tool()
def register_playlist(playlist_path: str) -> Dict[str, Any]:
    """
    Register local audio files listed in an M3U/M3U8 playlist.

    Relative entries are resolved against the playlist's directory. Full paths
    are never returned; entries contain only tokens, display names, and line
    numbers.
    """
    try:
        entries = parse_m3u_playlist(playlist_path)
    except FileNotFoundError:
        return {"error": "Playlist not found"}
    except PermissionError:
        return {"error": "Unable to access playlist"}
    except OSError:
        return {"error": "Unable to read playlist"}
    except ValueError as error:
        if str(error) == "Unsupported playlist format":
            return {"error": "Unsupported playlist format"}
        return {"error": "Unable to resolve playlist"}
    except RuntimeError:
        return {"error": "Unable to resolve playlist"}

    registry = get_registry()
    registered: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for line_number, entry_path, skip_reason in entries:
        if skip_reason:
            skipped.append({"line": line_number, "error": skip_reason})
            continue

        if entry_path is None:
            skipped.append({"line": line_number, "error": "Invalid playlist entry"})
            continue

        try:
            result = registry.register(str(entry_path))
            registered.append({"line": line_number, **result})
        except FileNotFoundError:
            skipped.append({"line": line_number, "error": "File not found"})
        except OSError:
            skipped.append({"line": line_number, "error": "Unable to access file"})
        except (RuntimeError, ValueError):
            skipped.append({"line": line_number, "error": "Unable to resolve file"})

    return {"registered": registered, "skipped": skipped}


# ---------------------------------------------------------------------------
# Tool 3: Read metadata via token (path never returned)
# ---------------------------------------------------------------------------

@app.tool()
def read_track_metadata(token: str) -> Dict[str, Any]:
    """
    Read metadata and audio stream specs (duration, bitrate, format, tags) for
    a registered file identified by its token.

    The file path is resolved internally and is never included in the response.
    """
    registry = get_registry()
    path = registry.resolve(token)
    meta = read_audio_metadata(str(path))
    # Strip the path fields before returning
    meta.pop("file_path", None)
    return meta


# ---------------------------------------------------------------------------
# Tool 4: Extract filename clues (stateless, no paths)
# ---------------------------------------------------------------------------

@app.tool()
def extract_filename_clues(token: str) -> Dict[str, Any]:
    """
    Extract investigative clues from the file's bare display name:
    track numbers, artist guesses, title guesses, years, and bracketed notes
    (e.g., regional markers, live venues, catalog numbers).
    """
    registry = get_registry()
    entry = registry.resolve(token)
    return extract_clues_from_filename(entry.name)


# ---------------------------------------------------------------------------
# Tool 5: Batch Brief (high density inspection for multi-track batches)
# ---------------------------------------------------------------------------

@app.tool()
def get_batch_brief(tokens: List[str]) -> List[Dict[str, Any]]:
    """
    Generate a comprehensive investigative brief for a list of registered tokens.
    Returns format, duration, existing tags, and filename clues for each token in one call.
    """
    registry = get_registry()
    briefs = []
    for tok in tokens:
        try:
            p = registry.resolve(tok)
            meta = read_audio_metadata(str(p))
            meta.pop("file_path", None)
            clues = extract_clues_from_filename(p.name)
            briefs.append({
                "token": tok,
                "display_name": p.name,
                "duration_seconds": meta.get("duration_seconds"),
                "format": meta.get("format"),
                "tags": meta.get("tags", {}),
                "filename_clues": clues,
            })
        except Exception as e:
            briefs.append({"token": tok, "error": str(e)})
    return briefs


# ---------------------------------------------------------------------------
# Tool 6: Mojibake repair (stateless, no paths)
# ---------------------------------------------------------------------------

@app.tool()
def repair_mojibake(text: str) -> Dict[str, Any]:
    """
    Detect and repair corrupted character encoding (Mojibake).
    Specialized for Soviet/Russian Cyrillic (Windows-1251 misread as Latin-1)
    and Japanese Shift-JIS/CP932.
    """
    return fix_mojibake(text)


# ---------------------------------------------------------------------------
# Tool 7: MusicBrainz forensic search (stateless, no paths)
# ---------------------------------------------------------------------------

@app.tool()
def search_canonical_release(
    artist: str,
    title: str,
    duration_sec: Optional[float] = None,
    clue: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Search MusicBrainz for matching recordings and rank releases forensically.
    Uses track duration matching (±2.5s for exact match) and optional context
    clues (venues, years, album subtitles) to classify releases.
    """
    return search_recordings_forensic(
        artist=artist,
        title=title,
        duration_sec=duration_sec,
        clue=clue,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Tool 8: Verify MBID / Eval Gate (stateless, no paths)
# ---------------------------------------------------------------------------

@app.tool()
def verify_mbid(
    recording_id: str,
    expected_artist: Optional[str] = None,
    expected_title: Optional[str] = None,
    duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Evaluation Gate: Validates a hypothesized MusicBrainz Recording ID against
    ground truth expected title, expected artist, and exact audio duration.

    Returns confidence score (0-100), duration difference, release list,
    and any mismatch warnings before staging tag changes.
    """
    return verify_recording_mbid(
        recording_id=recording_id,
        expected_artist=expected_artist,
        expected_title=expected_title,
        duration_sec=duration_sec,
    )


# ---------------------------------------------------------------------------
# Tool 9: Preview tag changes (reads file via token, writes nothing)
# ---------------------------------------------------------------------------

@app.tool()
def preview_tags(token: str, new_tags: Dict[str, Any]) -> Dict[str, Any]:
    """
    Preview a field-by-field diff of proposed tag changes against a file's
    current metadata — without writing anything to disk.

    Accepted tag keys: title, artist, album, album_artist, track_number,
    year, original_year, musicbrainz_track_id, musicbrainz_release_id.

    The file path is resolved internally and never returned.
    """
    registry = get_registry()
    path = registry.resolve(token)
    result = preview_tag_changes(str(path), new_tags)
    # Ensure path is not leaked via the result dict
    result.pop("file_path", None)
    return result


# ---------------------------------------------------------------------------
# Tool 10: Stage tag changes (writes manifest only, NO audio file writes)
# ---------------------------------------------------------------------------

@app.tool()
def stage_tag_changes(
    token: str,
    new_tags: Dict[str, Any],
    mb_recording_id: Optional[str] = None,
    mb_release_id: Optional[str] = None,
    forensic_score: Optional[float] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Stage proposed tag changes for a registered file.

    This tool writes a pending-change manifest to a local directory.
    It does NOT modify any audio file. The agent receives a stage_id UUID
    and a human-readable summary. The file path is never returned.

    To apply staged changes, the user must run:
        python -m musicbee_tagger_mcp.apply_staged --stage-id <uuid>
    """
    registry = get_registry()
    staging = get_staging_manager()

    entry = registry.resolve(token)         # KeyError if token unknown
    display_name = entry.name

    return staging.stage(
        absolute_path=entry,
        display_name=display_name,
        proposed_tags=new_tags,
        mb_recording_id=mb_recording_id,
        mb_release_id=mb_release_id,
        forensic_score=forensic_score,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Tool 11: List all pending staged changes (safe fields only)
# ---------------------------------------------------------------------------

@app.tool()
def list_staged_changes() -> List[Dict[str, Any]]:
    """
    List all pending staged tag changes that have not yet been applied.

    Returns stage_ids, display names, timestamps, and diff summaries.
    File paths are never included.
    """
    return get_staging_manager().list_pending()


# ---------------------------------------------------------------------------
# Server entrypoint
# ---------------------------------------------------------------------------

def main():
    """Main entrypoint for MCP stdio transport."""
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
