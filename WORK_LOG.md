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
4. **Security & Physical Write Isolation**:
   - Agent operates strictly on opaque UUID tokens (`register_files(paths) -> tokens`).
   - Absolute filesystem paths are never exposed to the agent or in logs.
   - MCP server has zero write access to audio files. The agent can only *stage* proposed changes (`stage_tag_changes`).
   - Only the user can commit changes via interactive CLI confirmation (`python -m musicbee_tagger_mcp.apply_staged`).
5. **In-Window Investigator Agent (Zero Extra LLM Cost)**:
   - Packaged as an Antigravity Skill (`.agents/skills/musicbee-investigator/SKILL.md`).
   - The user + agent work interactively inside Antigravity using free window tokens, web search tools, and MCP forensic inspection.

---

## 🛠️ Environment & Paths
* **Repository Path**: `C:\Users\niccy\.gemini\antigravity\scratch\musicbee-tagger-mcp`
* **Worktree Path**: `C:\Users\niccy\.gemini\antigravity\worktrees\musicbee-tagger-mcp\musicbee_metadata_bridge`
* **GitHub Remote (Private)**: `git@github.com:niccy266/musicbee-tagger-mcp.git`
* **Python Version**: Python 3.14
* **Virtual Environment**: `.venv` in repository root

---

## 🏗️ Architecture & Component Map

```
musicbee_metadata_bridge/
├── .agents/
│   └── skills/
│       └── musicbee-investigator/
│           └── SKILL.md           # Antigravity skill playbook for detective agent
├── src/
│   └── musicbee_tagger_mcp/
│       ├── __init__.py
│       ├── server.py              # FastMCP server exposing 10 read-only/staging tools
│       ├── file_registry.py       # Session-scoped token ↔ path indirection (paths never leak)
│       ├── staging.py             # Manifest staging manager (%APPDATA%\musicbee-tagger-mcp\staged)
│       ├── apply_staged.py        # User CLI tool for interactive review & commits (ONLY write path)
│       ├── metadata_reader.py     # Mutagen wrapper (ID3v2.4, Vorbis OGG/FLAC, MP4/M4A)
│       ├── filename_parser.py     # Regex clue extractor (brackets, years, track #, artist/title guess)
│       ├── mojibake.py            # Encoding repair heuristics (CP1251 <-> Latin1, Shift-JIS, ftfy)
│       ├── musicbrainz_client.py  # Forensic search + verify_recording_mbid (Eval gate)
│       └── tag_writer.py          # Safe tag applicator with diff preview & backup
└── tests/
    ├── test_tagger.py             # Charsets, mojibake, duration scoring, release classification
    ├── test_secure_pipeline.py    # Token concealment, path safety, and zero-write server surface
    └── test_investigator_tools.py # Filename parsing, string similarity, and MBID eval gate
```

---

## 🛡️ MCP Tools Surface (10 Tools)

1. `register_files(paths: list[str])` -> Ingests paths, returns `[{"token": "uuid", "display_name": "filename"}]`.
2. `read_track_metadata(token: str)` -> Format, technical specs, existing tags (no paths returned).
3. `extract_filename_clues(token: str)` -> Structured hints from filename (brackets, year, track #, artist/title).
4. `get_batch_brief(tokens: list[str])` -> High-density brief combining metadata and clues for batch triage.
5. `repair_mojibake(text: str)` -> Fixes CP1251/Latin-1 or Shift-JIS corruption.
6. `search_canonical_release(...)` -> Lucene query + duration proximity scoring.
7. `verify_mbid(recording_id, ...)` -> **The Eval Gate**: confirms recording title, artist, duration match (<2.5s), and releases.
8. `preview_tags(token: str, new_tags: dict)` -> Field-by-field diff preview.
9. `stage_tag_changes(token: str, new_tags: dict, ...)` -> Writes staging manifest to disk, returns `stage_id`.
10. `list_staged_changes()` -> Lists pending staged changes without leaking paths.

---

## 🚀 How to Run

### 1. Run Unit Tests (22/22 Passing)
```powershell
cd C:\Users\niccy\.gemini\antigravity\scratch\musicbee-tagger-mcp
.\.venv\Scripts\Activate.ps1
pytest -v
```

### 2. User Review & Apply CLI (The Only Code Path that Modifies Files)
```powershell
# List pending changes
python -m musicbee_tagger_mcp.apply_staged --list

# Review and apply one track interactively
python -m musicbee_tagger_mcp.apply_staged --stage-id <uuid>

# Review all pending tracks interactively (with dry-run option)
python -m musicbee_tagger_mcp.apply_staged --all --dry-run
python -m musicbee_tagger_mcp.apply_staged --all
```

---

## 📝 Work & Decision Log

### 2026-10-23
- Initialized Git repository, `.gitignore`, and `pyproject.toml`.
- Implemented `mojibake.py`, `metadata_reader.py`, `musicbrainz_client.py`, `tag_writer.py`, and `server.py`.
- **Security Refactor**:
  - Implemented `file_registry.py`: opaque UUID tokens replace paths across all tools.
  - Implemented `staging.py` & `apply_staged.py`: strictly two-phase commit. MCP server has zero write tools.
  - Stripped `file_path` from all tool responses to prevent path leakage to agents or prompt logs.
- **Investigator & Eval Infrastructure**:
  - Implemented `filename_parser.py`: extracts bracketed clues (e.g. `(静岡)`), years, and title/artist guesses.
  - Implemented `verify_recording_mbid`: built-in verification gate calculating duration proximity and string similarity before staging.
  - Implemented `get_batch_brief`: single-turn multi-track batch inspection tool.
  - Created Antigravity skill at `.agents/skills/musicbee-investigator/SKILL.md` for in-window zero-cost detective sessions.
- All 22 test cases passing.

### 2026-10-23 — Investigator follow-up
- Confirmed the active repository is `K:\dev\vibe-coding\musicbee-mcp-server` on branch `claude-session` (five commits ahead of `origin`); the working tree was clean before this follow-up. The three handoff sample audio files are present.
- Read sample metadata through the token-based batch brief. Durations: “The Sunshine Of Marseilles” 166.277s, “The Knack (Main Theme)” 174.681s, and “I'd Be A Millionaire” 214.056s. The filename clue parser reverses the artist/title guesses for these filename patterns, so the embedded tags were used for searches.
- MusicBrainz searches did not find candidates for the Sunshine or David tracks. A broad John Barry search returned a “The Knack” recording (MBID `aaf8c36e-11fb-49f1-8032-6e2b4030ceb0`, 176.81s). It has not been confirmed as the local “The Knack (Main Theme)” version: the successful live verification compared against the shorter expected title “The Knack”, so a verification using the full local title remains necessary.
- Fixed the verifier request to use the `musicbrainzngs` library's supported recording includes (`artists` and `releases`); added an assertion for those includes. Added a conservative `Unknown` classification when release-group type metadata is missing, rather than assuming “Studio Album”; added regression coverage.
- Validation: `tests/test_investigator_tools.py` passes (7 tests); `git diff --check` passes. No tags were staged or applied and no audio files were modified.
- MusicBrainz entity model and tool implications:
  - A **recording** identifies a particular audio version/performance (including a mix or edit); it carries the recording title, artist credit, duration, and recording MBID. This is the level our search ranks and our verification gate checks against the local file.
  - A **release** is a concrete issue/edition (such as a particular country's/date/label/format issue) and has its own release MBID. A recording can occur on many releases, with track placement and release-specific details.
  - A **release group** is the abstract album/single/EP grouping for related releases. Its primary type (Album, Single, EP, etc.) and secondary types (such as Compilation, Soundtrack, or Live) are useful for choosing the right album context; they are not the recording ID and do not identify one specific pressing.
  - The forensic search reads release and nested release-group data when present and uses it to describe candidate release context. The verifier fetches the recording and its releases, then picks a preferred release for the proposed tags. In the installed `musicbrainzngs` version, `get_recording_by_id` does not accept `release-groups` in its validated include list, even though the MusicBrainz API docs list release-groups as a recording subquery. Consequently, that lookup returned releases without nested release-group type data in the live check; those releases must stay `Unknown` rather than being misrepresented as studio albums. Obtaining group metadata reliably may require fetching a release with its release-group include or updating the client/library path.
- References: [MusicBrainz Database Schema](https://musicbrainz.org/doc/MusicBrainz_Database/Schema), [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API).
- MCP follow-up: The session did not expose the MusicBee server as a directly callable tool. Launched the repository's local server over MCP stdio and called `register_files` plus `get_batch_brief` for the three sample files. The first client-side attempt misread the SDK result envelope; after correcting it to read `structured_content["result"]`, the batch brief succeeded and returned the tags and durations above. No tag-writing or staging tool was called.
- Filename parser and token-system clarification: `FileRegistry` maps each registered absolute path to a random UUID held in the server process; subsequent metadata/clue tools resolve that token internally. The clue extractor receives only the basename and returns the basename plus heuristic clues (track number, year, brackets, and a first-two-parts split that assumes `Artist - Title`). It is useful as supplementary evidence, not as a reliable authority for artist/title order; the sample filenames use the opposite order. It hides directory paths, not the filename itself. Privacy edge case found during inspection: a failed registration currently returns the `FileNotFoundError` message containing the submitted path. This was documented but not changed in this follow-up.
