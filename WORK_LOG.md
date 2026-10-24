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
* **Repository Path**: repository root (`.`)
* **Worktree Path**: separate worktree named `musicbee_metadata_bridge` (location depends on the user's environment)
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
│       ├── server.py              # FastMCP server exposing 11 read-only/staging tools
│       ├── file_registry.py       # Session-scoped token ↔ path indirection (paths never leak)
│       ├── playlist.py            # M3U/M3U8 parsing and relative path resolution
│       ├── staging.py             # Manifest staging manager (user application-data directory: musicbee-tagger-mcp/staged)
│       ├── apply_staged.py        # User CLI tool for interactive review & commits (ONLY write path)
│       ├── metadata_reader.py     # Mutagen wrapper (ID3v2.4, Vorbis OGG/FLAC, MP4/M4A)
│       ├── filename_parser.py     # Regex clue extractor (brackets, years, track #, artist/title candidates)
│       ├── mojibake.py            # Encoding repair heuristics (CP1251 <-> Latin1, Shift-JIS, ftfy)
│       ├── musicbrainz_client.py  # Forensic search + verify_recording_mbid (Eval gate)
│       └── tag_writer.py          # Safe tag applicator with diff preview & backup
└── tests/
    ├── test_tagger.py             # Charsets, mojibake, duration scoring, release classification
    ├── test_secure_pipeline.py    # Token concealment, path safety, and zero-write server surface
    ├── test_playlist.py           # M3U parsing, relative resolution, and safe registration
    └── test_investigator_tools.py # Filename parsing, string similarity, and MBID eval gate
```

---

## 🛡️ MCP Tools Surface (11 Tools)

1. `register_files(paths: list[str])` -> Ingests paths, returns `[{"token": "uuid", "display_name": "filename"}]`.
2. `register_playlist(playlist_path: str)` -> Resolves local M3U/M3U8 entries and returns tokens plus safe skip reasons.
3. `read_track_metadata(token: str)` -> Format, technical specs, existing tags (no paths returned).
4. `extract_filename_clues(token: str)` -> Structured hints from filename (brackets, years, track #, artist/title candidates).
5. `get_batch_brief(tokens: list[str])` -> High-density brief combining metadata and clues for batch triage.
6. `repair_mojibake(text: str)` -> Fixes CP1251/Latin-1 or Shift-JIS corruption.
7. `search_canonical_release(...)` -> Lucene query + duration proximity scoring.
8. `verify_mbid(recording_id, ...)` -> **The Eval Gate**: confirms recording title, artist, duration match (<2.5s), and releases.
9. `preview_tags(token: str, new_tags: dict)` -> Field-by-field diff preview.
10. `stage_tag_changes(token: str, new_tags: dict, ...)` -> Writes staging manifest to disk, returns `stage_id`.
11. `list_staged_changes()` -> Lists pending staged changes without leaking paths.

---

## 🚀 How to Run

### 1. Run Unit Tests (22/22 Passing)
```powershell
Set-Location .
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
- Confirmed the active repository root on branch `claude-session` (five commits ahead of `origin`); the working tree was clean before this follow-up. The three handoff sample audio files are present.
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

### 2026-10-23 — Parser ambiguity and registration privacy
- Changed separated filename parsing to return both artist/title interpretations in `artist_title_candidates` and leave `artist_guess`/`title_guess` unset rather than silently asserting an ordering. Multiple separator segments after the first are retained together in the second part. Updated the investigator skill to treat these alternatives as clues and prefer corroboration.
- Sanitized registration failures: missing files return `File not found`; other filesystem `OSError`s return `Unable to access file`. Error responses no longer include submitted paths.
- Added regression tests for both parser orders, the handoff's “The Knack” filename, and path-free missing/permission error responses.
- Validation: full test suite passes (26 tests). The first run used pytest's default temp root and encountered Windows `PermissionError` under the user's temp directory; rerunning with a new repository-local `--basetemp .pytest-basetemp` passed. `git diff --check` also passes. No sample audio was changed.

### 2026-10-23 — Investigator-agent MCP simulation
- Delegated a bounded simulation using only the local MCP server's `register_files`, `get_batch_brief`, and `extract_filename_clues` tools; prohibited direct file inspection, external search, and staging.
- The first MCP stdio attempt failed because the filename containing an invisible U+200E mark could not be encoded using the default Windows console encoding. Retrying with UTF-8 stdio succeeded.
- The agent received all three metadata briefs and ambiguous filename candidate pairs. Tag values and durations matched the prior MCP batch call; album/year/track/disc/MusicBrainz ID fields were empty, and all genres were `Другое`. No search, preview, staging, or apply tool was called; no audio was modified.
- Observed parser limitations from the MCP interaction: `_1` is not reported as a track number, and the invisible U+200E remains in the third file's artist tag. These are logged for future consideration; no code change was made as part of this simulation.

### 2026-10-23 — M3U playlist batch registration
- Added `register_playlist(playlist_path)` MCP tool. It reads local `.m3u`/`.m3u8` files, handles UTF-8 BOM and falls back to Windows-1252, resolves relative entries against the playlist folder, and passes supported local audio paths to the existing token registry.
- Returns registered tokens and bare display names with playlist line numbers. Missing/unreadable entries, remote URLs, and unsupported file types receive path-free skip reasons. Playlist read/resolve failures return generic errors; no playlist or audio paths are returned.
- Updated the investigator skill and MCP tool inventory. Added playlist parser/registration tests for relative entries, comments, BOM, unsupported/remote entries, missing files, path concealment, and invalid playlist extensions.
- End-to-end MCP stdio check: a temporary playlist referencing all three sample audio files registered three tokens; `get_batch_brief` returned the expected titles, artists, tags, and durations with no skipped entries.
- Validation: full suite passes (31 tests). The first full run found a test fixture setup error (the test wrote into a nonexistent parent directory); fixed the fixture and reran successfully. `git diff --check` passes. No playlist or audio files remain from the integration check, and no audio was modified.
- During the Strange Tags playlist task, inspection found staged diffs were read from a nonexistent `changes` field although tag preview returns `diff`; this could produce empty change summaries. Updated staging to convert only changed preview fields into the CLI/MCP diff-summary format and added regression coverage. Targeted secure-pipeline and playlist tests pass (18 tests).

### 2026-10-23 — Strange Tags playlist investigation and staging
- Registered all 24 playlist entries through the local MCP server; none were skipped. The playlist path was supplied only to `register_playlist`, and no subagent was used. All later inspection and verification used opaque file tokens.
- Staged 12 tracks for user review after checking MusicBrainz recording candidates. Reported confidence and local-to-MusicBrainz duration differences:
  - “Aline Cherie” — 98.5%, 0.09s; corrected the artist credit and added the recording ID.
  - “Crazy 'bout You” — 92.0%, 0.04s; corrected the title and added the recording ID.
  - “Crazy, Man, Crazy” — 85.7%, 0.02s; corrected artist/title and added the recording ID.
  - “I Go To Sleep” — 98.0%, 2.00s; identified as the demo version and added the recording ID.
  - “King of the Jungle” — 100.0%, 0.20s; added the recording ID.
  - “Oh My Love” — 98.3%, 0.70s; corrected the artist credit and added the recording ID.
  - “Sad Hasselhoff vs. The Panopticon” — 100.0%, 0.12s; normalized the title and added the recording ID.
  - “(Si Si) Je Suis Un Rock Star” — 98.5%, 1.67s; corrected the title and added the recording ID.
  - “Trippy” — 100.0%, 0.04s; added the recording ID.
  - “Wake Me Up Before You Go-Go” — 95.2%, 1.18s; corrected the artist/title and added the recording ID.
  - “Young and Beautiful” — 100.0%, 0.00s; normalized the title and added the recording ID.
  - “Only You” — 87.6%, 2.50s; corrected title and artist credit. The stage records the recording ID as verification metadata, but the proposed audio-tag changes are title/artist only; album/release tags were left unchanged.
- Did not stage four other candidate matches: “Arrow Through Me” fell below the confidence threshold and had an artist mismatch; “The Knack” had insufficient artist-credit similarity; “Search and Destroy” matched a live release despite the local “Raw Power” album tag, while the studio candidate had no duration; and “Truth” had a plausible title/duration match but conflicting artist/release context.
- Searches found no sufficiently credible candidate for the remaining eight tracks. These are unresolved, not evidence that no MusicBrainz recording exists. Search responses also produced `musicbrainzngs` XML warnings for newer/unknown MusicBrainz elements; some requests had intermittent service errors.
- Confirmed that the staging list contains 12 pending proposals with path-free display names and diffs. No audio files were modified; user review and the explicit CLI apply step are still required. Genre corrections were not attempted because genre is not currently supported by the tag-writing pipeline.

### 2026-10-23 — Investigator workflow and MusicBrainz API efficiency
- Updated the investigator skill with explicit path-safe delegation rules, token-registry checks before subagent MCP work, a compact single-session batch workflow, deliberate web corroboration for weak/conflicting matches, and a reminder not to stage unverified release-level fields.
- Updated project instructions to honor context-isolated investigator requests without exposing playlist paths, explicitly use web research when warranted, reuse batch MCP sessions, respect rate limits, and avoid oversized/repeated outputs.
- Researched the official MusicBrainz API documentation. The Search API accepts one required Lucene `query` per request and supports paging with `limit` (1–100) and `offset`; it does not document a multi-query/batch-search request. Lucene boolean expressions can combine terms in one search, but that does not create independently ranked per-track result sets and is unsuitable for mixing unrelated track searches. The API's `inc` option combines related entity subqueries for one requested entity; it is not a multi-root lookup.
- MusicBrainz documents a limit of one request per second per client and warns that excess traffic may be blocked. A client-side batch MCP tool could reduce agent/tool orchestration overhead, but must still send distinct MusicBrainz searches sequentially under that limit. For substantially larger-scale/offline workloads, official database dumps plus replication are an alternative, but are operationally excessive for a normal personal playlist.
- References reviewed: [MusicBrainz API Search](https://musicbrainz.org/doc/MusicBrainz_API/Search), [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API), [MusicBrainz API Rate Limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting), and [MusicBrainz Database Download](https://musicbrainz.org/doc/MusicBrainz_Database/Download).
- Added a persistent-state/database evaluation proposal to `docs/index.html`: benchmark actual bottlenecks first, prefer evaluating SQLite for local single-user persistence, and reserve PostgreSQL for justified multi-user/shared-service requirements with authentication, isolation, migrations, and backups planned.

### 2026-10-24 — Split server, MusicBrainz, staging, and tag-write responsibilities
- Reduced `server.py` to MCP app assembly and the stdio entrypoint. Moved MCP handlers into `tools/` modules for file registration, metadata inspection, MusicBrainz, tag preview/staging, and text repair. Kept server-level handler imports for existing callers and preserved all 11 registered tool names.
- Replaced the MusicBrainz implementation module with a compatibility facade; moved shared classification/scoring, recording search, and MBID verification into focused modules and centralized client User-Agent setup.
- Separated manifest filesystem operations into `stage_manifest_store.py`; `staging.py` now only creates proposals and returns safe pending summaries. Moved applying staged manifests into `staged_apply.py`, which alone imports the audio mutation service.
- Split read-only preview from physical tag writes: `tag_writer.py` remains a compatibility facade for preview only, while `tag_applier.py` dispatches to format-specific write helpers. MCP tool modules do not import the audio write implementation.
- Removed an unreachable duplicate block in metadata tag extraction found while checking module boundaries.
- Updated regression coverage for registration tool module locations, the exact MCP tool surface, and CLI-only application. Validation: full suite passes (32 tests); MCP smoke check confirms all 11 tools register and write modules are not imported by the server; HTML parser and `git diff --check` pass. No audio files were modified.

### 2026-10-24 — Local desktop release handoff plan
- Created `docs/LOCAL_DESKTOP_RELEASE_PLAN.md` as a fresh-agent handoff covering local Python package installation, user-level Claude Code configuration, a `K:\bin` launcher, configurable private state folders, path-free logging, retryable search manifests, confidence routing, explicit CLI-only audio writes, phased delivery, acceptance checks, and open implementation decisions.
- Captured user preferences: single-user Windows desktop; Python package; user-level Claude Code-style configuration; install root under `K:\tools\mcp-servers\musicbee-tags\`; launcher under `K:\bin\`; configurable private state root with that requested default; path concealment; and path-free applied/search logs.
- Documented confidence bands as initial heuristic routing proposals, not probabilities. Auto-stage never means write audio. Physical edits remain user-controlled via the CLI unless separately redesigned and explicitly approved.
- No runtime code or audio files changed.

### 2026-10-24 — Windows release package and Claude Code integration
- Added a Windows release installer that creates a dedicated virtual environment, installs a wheel, preserves the separate `data` directory, and generates MCP/apply launchers under `K:\bin`.
- Added a configurable `MUSICBEE_TAGGER_DATA_DIR` for staged manifests. Removed the silent temporary-directory fallback and made data-root access failures explicit without returning the configured path.
- Added a standalone Claude Code user-scope MCP config and a Claude Code plugin manifest/config using the official plugin layout. Both invoke the stable Windows launcher and set the same private data root.
- Added a local Claude Code marketplace catalog so the plugin can be installed persistently through the supported plugin manager workflow.
- Added a distributable README, a repeatable release builder for wheel, source distribution, plugin archive, and Windows release bundle, and aligned the human guide.
- Added regression tests for configured data-root selection and path-sanitized failures. No audio files were modified.
- Validation: all 36 tests pass; changed Python files score 10/10 in Pylint with the pre-existing broad-exception warning excluded; built the wheel, source distribution, plugin archive, marketplace archive, and Windows bundle; installed the wheel into an isolated test location; confirmed the generated launcher completes MCP initialization and exposes the existing 11 tools without an apply/write tool. The Claude CLI is not installed here, so interactive plugin installation could not be exercised.

### 2026-10-24 — Correct Pylint CI environment and scope
- Updated the Pylint workflow to install the project and its development dependencies from `pyproject.toml`, eliminating unresolved-import noise caused by installing only Pylint.
- Limited lint scope to application source rather than mixing test-style diagnostics into the application score.
- Kept the full Pylint report and score visible as advisory output, while making Pylint errors a separate blocking step. Existing warnings remain visible for gradual cleanup rather than making every push fail on an unconfigured legacy baseline.
- Validation: the revised report completes with a 9.13/10 application-source score and no unresolved-import findings; the separate `--errors-only` gate passes.

### 2026-10-24 — Bundle investigator skill in Claude plugin
- Added the `musicbee-investigator` skill at the Claude plugin's root-level `skills/` directory and a regression test that keeps it synchronized with the project skill source.
- Clarified that the MCP server boundary does not prevent shell-based audio writes, and that unresolved candidates should be reported to the user because no MCP review-flagging tool exists.
- Bumped package and plugin metadata to `0.1.1`; updated the Windows install examples and documented refreshing an installed local marketplace plugin.
- Validation: all 37 tests pass, Pylint `--errors-only` passes, Claude Code plugin validation passes with marketplace metadata warnings, and the plugin/marketplace/Windows release archives build with the new skill.

### 2026-10-24 — Add persistent GitHub-hosted Claude marketplace
- Added a repository-root Claude marketplace catalog pointing to the maintained plugin directory on the `release-ready-mcp` branch.
- Updated installation guidance to distinguish local release-bundle snapshots from the GitHub-hosted marketplace and document migration/update commands.
- Added regression coverage for the root marketplace catalog. The local marketplace was confirmed to point into the extracted v0.1.0 bundle; future updates need a Git-backed source to follow repository commits.

### 2026-10-24 — Human-only persistent playlist registration
- Removed path-taking playlist/file registration from the MCP tool surface. Added a human-run local playlist registration command that reads a path from a separate terminal and outputs only tokens, bare filenames, and path-free skip reasons.
- Persisted token-to-path records under the configured data directory so MCP tools can resolve tokens across process restarts and logins for the same user/install. Added a confirmation-gated cleanup command for registration records.
- Sanitized metadata, preview, and staging errors at MCP boundaries to prevent file paths in tool responses. Updated investigator instructions, Windows launchers, release docs, and tests.
- Privacy boundary: this prevents paths from entering chat and MCP request/response payloads; it does not defend against arbitrary same-user shell access. A separate Windows service account is needed for that stronger threat model.
- Validation: all 44 tests passed, Pylint `--errors-only` passed, Claude marketplace validation passed with its existing missing-author warning, installer syntax parsed, and `git diff --check` passed. Built and inspected the 0.1.2 wheel, source distribution, Claude plugin/marketplace archives, and Windows bundle; the release-specific tests passed (5 tests).
- Added an installer preflight that refuses upgrades while this server executable is running, avoiding Windows file-lock failures before pip modifies the installed package. Updated the Windows bundle and upgrade instructions.
- Installed 0.1.2 locally, verified all four launchers and `pip check`, completed an MCP handshake with exactly nine tools, and smoke-tested the installed registration CLI using a synthetic playlist. Its output contained no test path, and the token resolved from a fresh registry instance; the existing registration-record count remained unchanged (zero).

### 2026-10-24 — Read-only Genre inventory pilot
- Inspected metadata for 25 user-registered tracks via the installed MCP server. Found 18 distinct non-empty Genre strings; examples include semicolon-delimited values, punctuation-heavy source/vendor text, placeholder strings, dates, and NUL-separated values.
- No genre was normalized or staged, and no audio was applied. The pilot supports defining cleanup rules based on actual Genre field structure before any changes are proposed.
### 2026-10-24 — Persistent shared operation queue
- Added a transactional SQLite queue under the configured private data directory. MCP clients sharing that data root can enqueue path-free operations, query by status/batch with pagination, and persist progress updates across restarts.
- Added validation against local filesystem paths, retained completed entries, and covered persistence, filtering, pagination, status updates, and path rejection with regression tests.
- Updated the human/MCP guide, README, and investigator skill to document the queue tools and storage behavior.
