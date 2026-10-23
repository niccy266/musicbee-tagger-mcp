# MusicBee Audio Tag & Scrobble Optimizer (MCP Bridge)

## 📌 Project Overview
A specialized metadata bridge connecting **MusicBee**, local audio files, and the **MusicBrainz** ecosystem to ensure flawless, scrobble-ready tagging for Last.fm and ListenBrainz.

### Key Objectives
1. **High Fidelity Encoding**: Native UTF-8 JSON-RPC transport via Model Context Protocol (MCP) to eliminate clipboard corruption and mojibake (e.g., Russian Cyrillic Windows-1251 vs UTF-8, Japanese Kana/Kanji).
2. **Forensic Album Resolution**: Using messy title strings, live venues, dates, and track durations as forensic clues to trace missing `Album` tags to canonical releases (MusicBrainz / Discogs).
3. **Scrobble Optimization**: Enforcing clean scrobble strings according to canonical rules:
   - Live album tracks: clean title, live context stored in the `Album` tag.
   - Studio bonus tracks: clean `(Live)` suffix preserved.
   - Distributor fluff (`(Remastered 2021)`, `- Single`) stripped.
4. **Two-Phase Architecture**:
   - **Phase 1 (Active)**: Standalone Python MCP Server using `mutagen`, `musicbrainzngs`, and `ftfy`.
   - **Phase 2 (Planned)**: C# MusicBee UI Plugin to send selected tracks directly into the MCP pipeline.

---

## 🛠️ Environment & Paths
* **Repository Path**: `C:\Users\niccy\.gemini\antigravity\scratch\musicbee-tagger-mcp`
* **GitHub Remote (Private)**: `git@github.com:niccy266/musicbee-tagger-mcp.git`
* **Convenience Shortcut**: `K:\dev\AntigravityScratchPad.lnk` (points to `C:\Users\niccy\.gemini\antigravity\scratch`)
* **Python Version**: Python 3.14
* **Virtual Environment**: `.venv` in repository root

---

## 🏗️ Architecture: Phase 1 (Python MCP Server)

### Directory Structure
```
musicbee-tagger-mcp/
├── .gitignore
├── WORK_LOG.md
├── pyproject.toml
├── src/
│   └── musicbee_tagger_mcp/
│       ├── __init__.py
│       ├── server.py              # FastMCP server entrypoint & tools
│       ├── metadata_reader.py     # Mutagen wrapper (ID3v2.4, Vorbis, MP4)
│       ├── mojibake.py            # Encoding repair heuristics (ftfy + custom rules)
│       ├── musicbrainz_client.py  # Forensic release search & recording matching
│       └── tag_writer.py          # Safe tag applicator with diff preview & backup
└── tests/
    └── test_tagger.py
```

### Exposing MCP Tools
1. `read_track_metadata(file_path: str)` -> Dict with tags, format, duration, bitrate, existing MBIDs.
2. `repair_mojibake(text: str)` -> Clean text + detected source encoding.
3. `search_canonical_release(artist: str, title: str, duration_sec: float = None, clue: str = None)` -> Ranked release candidates.
4. `preview_tag_changes(file_path: str, new_tags: dict)` -> Before/after field-by-field diff.
5. `apply_tags(file_path: str, new_tags: dict, create_backup: bool = True)` -> Writes UTF-8 tags to file.

---

## 📝 Work & Decision Log

### 2026-10-23
- Initialized Git repository at `C:\Users\niccy\.gemini\antigravity\scratch\musicbee-tagger-mcp`.
- Created shortcut at `K:\dev\AntigravityScratchPad.lnk` targeting the scratch directory.
- Created `.gitignore` and `pyproject.toml`.
- Implemented `mojibake.py` (Cyrillic CP1251 <-> Latin1, Japanese Shift-JIS/CP932, ftfy auto-repair).
- Implemented `metadata_reader.py` (Mutagen wrapper for MP3 ID3v2.4, FLAC Vorbis, MP4/M4A, stream duration/bitrate).
- Implemented `musicbrainz_client.py` (Forensic recording search, duration proximity scoring, release classification).
- Implemented `tag_writer.py` (Safe UTF-8 tag writing, diff preview, automatic `.bak` backups).
- Implemented `server.py` (FastMCP 2.x stdio server exposing 5 tools).
- Implemented test suite in `tests/test_tagger.py` (5/5 tests passing).
- Committed initial implementation to Git.

---

## 🚀 Running & Connecting the MCP Server

### 1. Manual CLI Test / Inspection
```powershell
cd C:\Users\niccy\.gemini\antigravity\scratch\musicbee-tagger-mcp
.\.venv\Scripts\Activate.ps1
pytest -v
```

### 2. MCP Client Configuration (e.g. Claude Desktop, Antigravity, or VS Code MCP)
Add to your client configuration JSON:
```json
{
  "mcpServers": {
    "musicbee-tagger": {
      "command": "C:\\Users\\niccy\\.gemini\\antigravity\\scratch\\musicbee-tagger-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "musicbee_tagger_mcp.server"]
    }
  }
}
```

