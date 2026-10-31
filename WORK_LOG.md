### 2026-10-30 — Issue #68: harden MCP tool wrappers for offline tests

- Updated `tools/musicbrainz.py` `get_release_tracklist` to omit `duration_seconds` when unknown, harden zero-media/404/transport paths, and resolve MusicBrainz client in a patch-friendly way.
- Updated `tools/acrcloud.py` to map provider failures to `E_PROVIDER_FAILED` (and missing credentials to `E_PROVIDER_NOT_CONFIGURED`).
- Updated `tools/text.py` to map `repair_mojibake` exceptions via `error_from_exception`.
- Updated `tools/tags.py` to validate field names and newline values before preview/stage.
- Updated `tools/queue.py` and `tools/operations.py` to return typed `E_*` errors for bad operation ids.
- Added compatibility aliases in `artist_validation.py` and `tools/operations.py`.
- Branch: codex/issue-68-tool-wrapper-tests.


### 2026-10-29 — Documentation/agent prompt consistency audit

- Added a visible, consistent rule to agent-facing docs and prompts: do not run shell commands (bash, cmd, powershell, python, etc.) without first making absolutely sure the required action cannot be performed using an existing exposed tool; prefer the exposed tool and use a shell only as a last resort with justification.
- Updated AGENTS.md, .github/copilot-instructions.md, both musicbee-investigator SKILL.md copies, prompts/openrouter_agent.md, and docs/OPENROUTER_AGENT.md.
- Investigated repository test state: current branch has 6 failures (2 added by recent error_codes work plus 4 pre-existing on master); documented without changing unrelated code.


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
- Implemented a shared persistent operation queue with SQLite storage for cross-tool state.
- Updated the human/MCP guide, README, and investigator skill to document the queue tools and storage behavior.
- Validation: 23 focused queue, privacy, and skill-sync tests passed; Pylint `--errors-only` and `git diff --check` passed. Full suite: 78 passed, 4 skipped, with two unrelated failures (missing external probe executable for an M4A fixture and the existing package/plugin version mismatch).

### 2026-10-24 — v0.2.0 field map, OpenAI SDK, and playlist jobs
- Field-map refactor: one canonical `FieldSpec` table driving ID3/Vorbis/MP4 read+write; 12 canonical fields over 53 format-native keys. Added sort fields (artist/title/album/album_artist → TSO2/TSOT/TSOA/TSOP, Vorbis, MP4 atoms) and Last.fm passthrough fields (lastfm_title/artist/url as TXXX/Vorbis/freeform). Documented in docs/field-map.md (#19).
- Real-file test suite (19 tests) covering read parity, Unicode/Cyrillic round-trips, corrupted tags, and fingerprint reconciliation on synthetic MP3/FLAC/M4A fixtures (#17).
- Security: invisible Unicode format characters stripped from string tags; ACRcloud pre-match decision recorded as issue #18 (Last.fm text-search fallback before paid fingerprinting).
- Switched `scripts/openrouter_agent_loop.py` from hand-rolled urllib to the official `openai` SDK against OpenRouter's endpoint, preserving attribution headers (#22, PR #23).
- Playlist-job architecture (PR #24, #25): registration is human-run CLI only; the MCP server is a pure token API serving `next_batch` (batches of 10), `complete_batch`, and `job_status` (counts only). No MCP tool accepts a filesystem location. Fixed `create_job` dropping the skipped-entry count.
- Release v0.2.0: tagged and published; release assets (Claude marketplace/plugin, Windows bundle, wheel, sdist) built with scripts/build_release.py and uploaded. `release-ready-mcp` branch fast-forwarded to v0.2.0.
- Repo health: version-alignment test caught stale 0.1.2 in plugin manifest, `__init__.__version__`, README, and launchers — all aligned to 0.2.0; merged via PR #21. CI green on master.
- Validation: 82 tests pass (1 skipped), pylint errors-only clean, CI success on master.

### 2026-10-25 — Shared queue schema consolidation
- Consolidated the historical agent-operation and batch-operation stores onto the same SQLite table to prevent incompatible schemas from making the queue depend on which MCP tool initialized it first.
- Added an in-place migration that preserves queued work from either prior schema, plus regression coverage for cross-API visibility, status updates, claiming, and completion.
- Updated the human/agent guide to describe only the registered batch-queue MCP tools and the shared persistent store.
- Validation: 14 focused queue tests passed; full suite excluding the unavailable ffmpeg-dependent test passed (94 passed, 3 skipped, 2 deselected).

### 2026-10-25 — Claude Desktop MCP Bundle
- Added a Claude Desktop `.mcpb` package using the MCPB `uv` runtime and versioned manifest; the bundle includes the Python project metadata and runtime source only.
- Extended the release builder to emit the standalone bundle and include it in the Windows release archive. Documented installation, the default private data directory, and the separate human-only playlist registration workflow.
- Removed the superseded operation-queue tool registration retained during the upstream merge so the active MCP surface matches the current SQLite-backed queue.
- Validation: release/privacy tests passed (22); the full suite passed (94 passed, 4 skipped) with the M4A conversion test deselected because `ffmpeg` is unavailable. Built and inspected `musicbee-tagger-mcp-0.3.0.mcpb` and the Windows release archive; the MCPB is a valid ZIP with the expected manifest and runtime files.

### 2026-10-25 — Discoverable playlist jobs
- Added a path-free MCP `list_jobs` tool that reports only jobs with pending work, including IDs, playlist display names, progress counts, and skipped-entry counts.
- Updated the agent loop to accept an optional job ID, auto-select the sole available job, and require an explicit ID when multiple jobs are pending.
- Updated the agent guide, MCP tool reference, release tool manifest, and regression tests.
- Validation: 33 focused job, MCP-surface, and release tests passed; the full suite passed (100 passed, 4 skipped) with the M4A conversion test deselected because `ffmpeg` is unavailable. Pylint passed with only the missing `openai` import diagnostic suppressed. A synthetic omitted-ID end-to-end smoke test selected and completed the sole job without an OpenRouter request.

### 2026-10-25 — v0.4.0 release builds
- Bumped package, Python runtime, MusicBrainz user-agent, Claude plugin, and Claude Desktop MCPB versions to 0.4.0; updated installation and bundle examples and added version-alignment regression coverage.
- Built fresh v0.4.0 wheel, source distribution, Claude plugin and marketplace archives, MCPB, and Windows release bundle.
- Validation: all 8 release asset/version tests passed. Verified wheel metadata, plugin and MCPB manifests, MCPB ZIP integrity and all 16 tools, and inclusion of the wheel and MCPB in the Windows archive.
- Addressed Claude Desktop review findings: made the MCPB data directory configurable (defaulting to the Windows installer’s shared data path), included the root README referenced by project metadata, and raised the MCP SDK minimum to 2.0.0 for the imported `MCPServer` API.
- Updated the MCPB guide to distinguish the extension’s configured data directory from the standalone server’s Windows default. Rebuilt all six v0.4.0 artifacts; MCPB CLI manifest validation passed, the release tests passed (8), and the full suite passed (101 passed, 4 skipped, 1 ffmpeg-dependent test deselected). Pylint `--errors-only` and `git diff --check` passed.

### 2026-10-25 — v0.4.1 Windows MCPB temp/cache fix
- Set the MCPB `TMP`, `TEMP`, and `TMPDIR` values to the extension directory, and moved `UV_CACHE_DIR` under that same directory so uv temporary-file persistence and cache operations stay on one volume.
- Bumped package, protocol user-agent, plugin, MCPB, and release example versions to 0.4.1. This is a release change because v0.4.0 still fails to install for users whose extension/cache/temp locations span Windows volumes.
- Validation: MCPB schema validation passed; all 101 tests passed (4 skipped, 1 ffmpeg-dependent test deselected); Pylint `--errors-only` and `git diff --check` passed. Rebuilt and checked all six v0.4.1 release artifacts, including MCPB manifest contents and ZIP integrity.

### 2026-10-25 — Playlist registration path argument
- Updated the local registration CLI to accept an optional quoted playlist path argument while preserving its interactive prompt when no argument is supplied; the Windows launcher already forwards arguments.
- Documented argument usage and reiterated that playlist paths remain local. Added coverage for argument-based registration and launcher forwarding.
- Validation: 28 focused playlist, job, and release tests passed; investigator skill copies are synchronized and `git diff --check` passed.

### 2026-10-25 — Install directly from source checkout
- Added a root `install.ps1` that builds a wheel from the current checkout in a temporary directory and invokes the existing Windows installer, so users can install without downloading or extracting a release archive.
- Documented direct source installation, Python/launcher requirements, and install-root overrides; added a regression test for wheel building and installer argument forwarding.
- Validation: full suite passed (103 passed, 4 skipped, 1 ffmpeg-dependent test deselected); PowerShell syntax parsed; local wheel build succeeded; end-to-end install into a disposable directory created all four expected launchers; `git diff --check` passed.

### 2026-10-25 — Claude Desktop uv cross-volume setup diagnosis
- Inspected Claude Desktop's local startup log for the v0.4.1 extension attempt. `uv sync` fails before server launch while persisting its interpreter cache (`os error 17`); the follow-on "No MCP config found" warning is because extension setup did not complete. The MCPB's `mcp_config.env` is applied after this setup phase and cannot fix the initial sync environment.
- Documented a process-scoped PowerShell workaround to set `TEMP`, `TMP`, and `UV_CACHE_DIR` to the same `%LOCALAPPDATA%\uv\cache` directory before launching Claude Desktop, then reinstalling the failed extension. No persistent Windows environment variables were changed.
- Validation: the PowerShell workaround block parses successfully; release/version tests passed (9), and `git diff --check` passed. Confirmed the diagnosed `uv sync` failure in Claude's local log occurs before MCP config environment is applied.

### 2026-10-25 — Playlist MCP tool recursion fix
- Fixed registered `next_batch`, `complete_batch`, and `job_status` handlers: their local function names shadowed module helpers and recursively called themselves instead of dispatching to the job store.
- Added a registered-callback regression test covering a 25-track claim, duplicate claim prevention, status, completion, and actionable unknown-job errors. No audio files are touched.
- Validation: full suite passed (104 passed, 4 skipped, 1 ffmpeg-dependent test deselected); Pylint `--errors-only` and `git diff --check` passed.

### 2026-10-25 — Force local wheel refresh in Windows installer
- The installed package remained stale after building the same 0.4.1 version: plain `pip install` skipped replacing the installed wheel, while the installer still printed success.
- Changed the Windows installer to force-reinstall only the supplied wheel without reinstalling dependencies, and added release coverage. This ensures source-checkout installs actually deploy code changes before live MCP testing.
- Validation: 21 focused installer and playlist job tests passed; Windows installer syntax parsed. Reinstalled the local connector and confirmed the installed package source no longer contains the recursive wrapper.
- Live test through the installed MCP stdio executable passed tool discovery, 25-track synthetic claim, in-progress status, duplicate-claim prevention, completion, and safe invalid-job response using an isolated temporary data directory. Read-only status checks confirmed the user's two real jobs remained at 896 and 25 pending, with zero in progress. No real playlist tracks were claimed; no audio files were read or modified.

### 2026-10-25 — Fix Claude Desktop cross-drive MCPB setup
- The user's repeat install still failed before server startup: Claude's initial `uv sync` attempted to inspect PATH's Python 3.14 interpreter and persist uv cache files across volumes. `mcp_config.env` settings are applied too late to affect this setup phase.
- Bumped the package, protocol user-agent, plugin, MCPB, and install examples to 0.4.2. The MCPB now pins its setup interpreter to Python 3.11 and sets a project-local uv cache so interpreter metadata and dependency cache writes stay alongside the extension.
- Documented the local stdio architecture: the extension starts the server locally and does not need an HTTPS proxy or separate remote server. Playlist registrations and audio remain on the user's machine.
- Validation: 9 release-asset tests passed; Pylint `--errors-only` and `git diff --check` passed. Built the v0.4.2 release artifacts and verified MCPB ZIP integrity, manifest version, Python pin, and project-local uv cache configuration. The full suite passed with the ffmpeg-dependent M4A tests deselected (104 passed, 3 skipped, 2 deselected); an unfiltered run confirmed the M4A conversion fails only because `ffmpeg` is not installed.

### 2026-10-25 — Correct MCPB cache placement after v0.4.2 failure
- The user's latest error path is under Claude's extension directory, confirming that v0.4.2's project-local `.uv-cache` redirected uv to the extension volume and did not avoid cross-volume temp-file moves.
- Bumped to 0.4.3, retained the Python 3.11 pin, removed the extension-local cache and temp environment overrides, and restored the standard Windows `%LOCALAPPDATA%\uv\cache` location for install-time `uv sync`.
- Updated release docs to clarify that this is a local stdio connector; HTTPS proxying would not affect the install-time interpreter/cache failure.
- Validation: release tests passed (9); Pylint `--errors-only` and `git diff --check` passed. Full suite passed with ffmpeg-dependent conversions deselected (104 passed, 3 skipped, 2 deselected). Built all six v0.4.3 release assets and verified MCPB ZIP integrity, version, Python 3.11 pin, absence of extension-local uv cache overrides, and preserved MCP data-directory configuration.

### 2026-10-25 — Align README with shared queue MCP tools
- Replaced outdated operation-claim API names with the registered batch queue tools (`enqueue_batch_operation`, `list_batch_operations`, and `update_batch_operation`) and clarified cross-restart visibility for agents sharing a data directory.
- Validation: 14 focused queue tests passed; `git diff --check` passed.

### 2026-10-26 — HTTPS Dockerized MCP connector (two-container sandbox)
- Added `Dockerfile.mcp`: HTTPS MCP server container, non-root user (uid 10001), read-only root filesystem, `/staging` and `/data` writable, `/audio` mounted read-only, exposes only port 8443, drops all capabilities, no-new-privileges.
- Added `Dockerfile.apply`: apply agent container, non-root user (uid 10002), no network, no exposed ports, `/staging` read-only, `/audio` read-write (only path that can modify audio files).
- Added `docker-compose.yml`: orchestrates both containers with shared `musicbee-staging` volume; MCP writes staged manifests, apply reads and applies to real audio; MCP container can reach MusicBrainz API, apply container is fully offline.
- Added `scripts/https_mcp_server.py`: HTTPS wrapper that runs the stdio MCP server as a subprocess and bridges HTTPS JSON-RPC (StreamableHTTP-compatible `/mcp` endpoint) to its stdio pipe; self-signed cert generation via `cryptography` or `openssl` fallback; TLS 1.2 minimum; health check at `/health`.
- Added `scripts/entrypoint_mcp.sh` and `scripts/entrypoint_apply.sh`: fix volume ownership on startup, then launch the HTTPS server or sleep infinity (apply container triggered via `docker compose exec`).
- Added `.env.example`: `MUSICBEE_AUDIO_DIR`, `MCP_HTTPS_PORT`, `SECRET_COMMAND_TOKEN`, `MUSICBEE_TAGGER_DATA_DIR`.
- Added `claude_desktop_config.example.json`: Claude Desktop HTTP MCP server config pointing at `https://localhost:8443/mcp`.
- Security model: MCP container never writes audio files (read-only mount); apply container is the sole write path and is triggered only by a secret user command (`docker compose exec musicbee-apply musicbee-tagger-apply --all` with `SECRET_COMMAND_TOKEN`); shared staging volume is the only cross-container data path.
- Validation: all new files parse correctly (Python AST for https_mcp_server.py, YAML for docker-compose.yml); `git diff --check` passed.

### 2026-10-25 — Update agent-loop model example
- Changed the documented default model in `scripts/openrouter_agent_loop.py` to `openrouter/free`.
- Validation: using the project virtual environment with `K:\bin` added to the test process PATH, the full suite passed (108 passed, 1 skipped). Pytest needed a workspace basetemp and `MUSICBEE_TAGGER_DATA_DIR` override for sandbox write access.


### 2026-10-26 — Prepare v0.4.3 release
- Updated the Windows installer to install the wheel's declared runtime dependencies before force-refreshing the wheel without reinstalling dependencies. This fixes fresh installs while preserving same-version source-checkout updates.
- Aligned the README queue-tool examples with the current MCP tools and carried forward the agent-loop model example and pytest temporary-directory ignore cleanup.
- Validation: full suite passed (111 passed, 1 skipped); Pylint `--errors-only`, installer syntax parsing, and `git diff --check` passed. A fresh isolated source install imported all runtime dependencies and launched the apply CLI help successfully. Built all six v0.4.3 release assets.

### 2026-10-26 — Preserve multi-value MusicBrainz genres (#30)
- Aggregated recording and release genre tags into a semicolon-delimited value in recording search and MBID verification results, deduplicating repeated labels while retaining recording-specific association.
- Preserved every multi-value genre read from ID3, Vorbis, and MP4 tags; undecodable byte values are decoded with replacement so additional genres are not dropped. ID3's NUL-separated genre form is normalized to the canonical semicolon separator. Genre writes split the canonical semicolon-delimited value back into native multi-value tag entries.
- Updated the MusicBrainz verification test to expect the genre-tag request used by the new aggregation behavior.
- Added coverage for MusicBrainz recording/release aggregation, garbled multi-value inputs, and multi-genre cross-format round trips.
- Validation: targeted tests passed (5 passed, 3 skipped because ffmpeg is unavailable); `git diff --check` passed. Audio files were not modified.

### 2026-10-26 — Windows Claude Desktop MCPB without uv (#31)
- Bumped package and extension metadata to 0.4.4 and added a Windows-specific MCPB that bundles the stdio server as a self-contained executable. Claude Desktop no longer needs to run uv during extension setup, avoiding the reported cross-drive temporary-file move failure and any dependency on finding Python on PATH.
- Kept the existing data-directory picker so the extension and local registration/apply tools can share the selected queue and token database. Documented that Claude manages the extension storage location separately.
- Added a Windows CI smoke test that builds the bundle and verifies MCP initialization and tool discovery from the packaged executable.
- Validation: release/package tests passed (11 passed, 1 skipped); full suite passed (116 passed, 2 skipped) with `K:\bin` added to the test process PATH. The executable smoke test is configured for Windows CI; it was skipped locally because PyInstaller is not installed in the current virtual environment.
### 2026-10-26 — Fix OpenRouter genre auto-inclusion indentation
- Corrected over-indented MusicBrainz genre auto-inclusion block in `scripts/openrouter_agent_loop.py` so it runs as part of stage verification handling instead of being unreachable inside the release-id assignment.
- Validation: `py_compile` passed; `tests/test_openrouter_agent_loop.py` passed (4 passed); `git diff --check` passed. No audio files were modified.

### 2026-10-26 — Expose all agent tools including ACRCloud and memory listing
- Added `identify_acrcloud` to the OpenRouter agent tool set and local dispatch, and added `list_tools`/`list_all_tools` so the agent can discover every available tool.
- Updated the system prompt to state that the agent may use all tools, including `identify_acrcloud`, `write_memory`/`append_memory`, and `list_tools`.
- Validation: `py_compile` passed; `tests/test_openrouter_agent_loop.py` passed (4 passed); `tests/test_secure_pipeline.py` passed (15 passed). No audio files were modified.



### 2026-10-26 — Add OpenRouter-backed context compaction and verify memory

- Added `compact_context_with_openrouter` (plus aliases) to compact context via a separate OpenRouter call that removes failures, failure mentions, and duplicate messages.
- Extended `compact_context` to delegate to the OpenRouter compaction path when model/api-key or opt-in flags are provided.
- Wired post-run compaction into the main batch loop, with `--compaction-model` and `--no-compact-context` options.
- Fixed `write_successes_to_memory` deduplication so repeated successes are not appended with new timestamps.
- Validation: full suite passed (167 passed, 1 skipped).

### 2026-10-27 — Fix read_track_metadata short-token resolution
- Added short-token (6-char) resolution to `file_registry.py` so tracks can be looked up by abbreviated tokens
- Added short-token handling in `tools/inspection.py`
- Added `tests/test_file_registry_short_tokens.py` with coverage for short-token registration and lookup

### 2026-10-27 — Guide agent to continue when track metadata read fails
- Updated `prompts/openrouter_agent.md` system prompt to guide the agent to skip stuck tracks and continue the batch loop instead of halting when a track metadata read fails

### 2026-10-27 — Add diagnostics for unexpected OpenRouter run termination
- Added run-termination diagnostics in `scripts/openrouter_agent_loop.py` to detect and report unexpected OpenRouter agent run endings
- Added diagnostic-related patterns to `.gitignore`

### 2026-10-27 — Harden MCP tag tools against unknown registry tokens
- Hardened `tools/tags.py` to handle unknown/unset registry tokens gracefully instead of erroring

### 2026-10-27 — Add token_ACRcloud_key to .gitignore
- Added `token_ACRcloud_key` to `.gitignore` so the ACRCloud secret file is never committed

### 2026-10-27 — Add path-safe reason codes to token metadata reads
- Added path-safe reason codes to `tools/inspection.py` token metadata reads so callers can distinguish safe vs. unsafe token resolution
- Updated `tests/test_secure_pipeline.py` accordingly

### 2026-10-27 — Log server version and configured data dir on startup
- Added startup logging in `server.py` that reports the server version and configured data directory

### 2026-10-27 — Bump release version to 0.4.5
- Bumped package version to 0.4.5 across `README.md`, `docs/index.html`, `pyproject.toml`, `.claude-plugin/plugin.json`, `release/mcpb/manifest.json`, `src/musicbee_tagger_mcp/__init__.py`, `src/musicbee_tagger_mcp/acrcloud.py`, `src/musicbee_tagger_mcp/musicbrainz_api.py`, `tests/test_release_assets.py`

### 2026-10-27 — Expose split tools in OpenRouter agent dispatch
- Refactored `scripts/openrouter_agent_loop.py` to expose split/individual tools in the agent dispatch table, replacing the monolithic tool approach
- Minor update to `artist_validation.py`

### 2026-10-27 — Fix ACRCloud secret file credential parsing
- Rewrote `ACRCloudConfig.from_env()` secret-file fallback to parse `token_ACRcloud_key` as `key=value` pairs, mapping `accessKey`→`access_key`, `secretKey`→`access_secret`, and `host`→`host` as three separate credentials per the ACRCloud docs
- Extracted `_load_secret_file()` helper supporting both `key=value` lines and JSON object formats, with `ACRCLOUD_SECRET_FILE` override
- Env vars continue to take precedence over file values; missing file returns empty defaults (unconfigured)
- Added tests: `test_config_from_secret_file_key_value`, `test_config_from_secret_file_env_vars_take_precedence`, `test_config_from_secret_file_missing_returns_defaults`
- Validation: all 11 tests in `tests/test_acrcloud.py` passed (including 3 new); `acrcloud.py` and `test_acrcloud.py` pass `ast.parse` syntax check

### 2026-10-27 — Standardized MCP error codes with path-free reporting
- Added `src/musicbee_tagger_mcp/error_codes.py` with stable `E_*` error codes (`E_UNKNOWN_TOKEN`, `E_FILE_NOT_FOUND`, `E_PERMISSION_DENIED`, `E_UNSUPPORTED_FORMAT`, `E_STAGING_FAILED`, `E_STAGE_NOT_FOUND`, `E_STAGE_CONFLICT`, `E_AUDIO_READ_FAILED`, `E_PROVIDER_FAILED`, `E_INTERNAL`, etc.)
- Added `make_error()` and `error_from_exception()` helpers that return `{"error_code", "error", "function?"}` dicts with automatic filesystem path stripping (Windows `C:\...` and POSIX `/...` replaced with `[path]`)
- Updated `tools/inspection.py`: `read_track_metadata`, `extract_filename_clues`, `get_batch_brief` now return error codes with function names
- Updated `tools/tags.py`: `preview_tags`, `stage_tag_changes`, `get_staged_change`, `amend_staged_changes`, `withdraw_staged_change` now return error codes with function names
- Updated `tools/acrcloud.py`: `identify_acrcloud` returns `E_UNKNOWN_TOKEN`, `E_AUDIO_READ_FAILED`, `E_PROVIDER_NOT_CONFIGURED` with function name
- Updated `tools/text.py`: `web_search` returns `E_PROVIDER_FAILED` with function name
- Added `tests/test_error_codes.py` (18 tests): error code mapping, path stripping, function name reporting, `extract_filename_clues` error handling
- Updated `tests/test_secure_pipeline.py` assertions to match new error code format
- Validation: all 18 new error code tests passed; full suite 185 passed, 4 skipped, 2 pre-existing failures (ffmpeg missing, tool name mismatch); no regressions

### 2026-10-28 — Streamline agent onboarding

- Updated system prompt: metadata and filename clues are pre-provided in the batch brief. Agent should skip read_track_metadata/extract_filename_clues and go straight to web_search and search_canonical_release.
- Updated tool descriptions in openrouter_agent_loop.py to mark read_track_metadata and extract_filename_clues as "ALREADY PROVIDED — do NOT call".
- PR #62 merged.

### 2026-10-28 — Close already-implemented issues

- Issue #40: preview_batch already implemented. Closed.
- Issue #41: release_batch already implemented. Closed.
- Issue #38: withdraw/amend staged changes already implemented. Closed.
- Issue #17: ACRCloud fingerprint fallback already implemented. Closed.
- Issue #29: Docker container with HTTP MCP already implemented. Closed.
- Issue #6: Stage-manifest persistence hardening already implemented. Closed.
- Issue #4: MusicBrainz verification gate already implemented. Closed.
- Issue #2: Path-safe error reporting already implemented. Closed.
- Issue #44: Case-insensitive search + variant filtering. PR #59 merged.
- Issue #42: Unresolved/partial batch outcomes. PR #60 merged.
- Issue #43: Release membership validation in evaluate_match. PR #58 merged.
- Issue #46: Release tracklist lookup. PR #61 merged.

### 2026-10-28 — Tackle issues #44, #42, #40, #43

- Issue #44: Made release search case-insensitive (title-cases all-caps/all-lowercase input) and filtered variant editions (isolated vocals, sped-up, slowed, reverb, nightcore, 8d audio, bass boosted). PR #59 merged.
- Issue #42: Support unresolved/partial outcomes in complete_batch (status field), job_status returns unresolved tracks separately, agent loop passes status. PR #60 merged.
- Issue #40: Already implemented (preview_batch). Closed.
- Issue #43: Added release_id parameter to evaluate_match for release membership validation. PR #58 merged.
- All CI jobs pass.

### 2026-10-28 — Fix agent NameError crashes and improve tool descriptions

- Fixed `NameError: compact_context_with_openrouter` by moving `__main__` block to end of file.
- Fixed `NameError: staged` in `main()` (changed to `staged_names`).
- Fixed `NameError: seen` in `review_scratchpad()` (added `seen = set()`).
- Freed alias assignments from string literal.
- Staging no longer requires `verified=true` — only requires `evaluate_match` called once.
- Improved MCP tool descriptions with NEXT STEP / PREREQUISITE guidance.
- Added `release_id` parameter to `evaluate_match` for release membership validation (issue #43).
- Added missing `error_codes.py` module.
- Updated test expectations for new error format.
- All 6 CI jobs pass on PR #58.

### 2026-10-28 — Verify merges, fix tool-surface regression, tidy leftovers
- Audited all remote branches: five `codex/*` branches were never merged (the last agent left them unmerged; no master work was displaced). Merged `workflow-trigger`, `websearch-fixes`, `artist-split-fixes`, `installer-process-shutdown`, `local-docs` into master.
- Fixed a released-tool regression: the server registered the renamed `evaluate_match` wrapper, so the published `verify_mbid` tool had disappeared from the MCP surface while the mcpb manifest, investigator skill, agent prompt and pinned tests all still called `verify_mbid`. `musicbrainz.py` now registers `verify_mbid` and keeps `evaluate_match` as the loop's internal alias.
- Merged `codex/batch-ergonomics` (#47 duplicate registration, #40 non-claiming `preview_batch`), resolving the `file_registry.py` conflict by keeping both the short-token matcher and `token_for_path`, and re-applying the branch's `register()` dedupe on top.
- Removed session scratch files `_fix_loop.py` and `CLAUDE_RULES.md`.
- Documented the agent loop's compaction/context flags (`--compaction-model`, `--no-compact-context`, `--context-chars`, `--thought-tokens`) and the full tool surface in `docs/OPENROUTER_AGENT.md`.
- Dropped a duplicated `web_search` entry in the pinned tool set in `tests/test_secure_pipeline.py`.
- Validation: 175 passed, 2 skipped.

### 2026-10-29 — Fix Windows path redaction, POSIX path regex corruption, and E_PARSE_ERROR mapping
- Fixed Windows path redaction regex in `src/musicbee_tagger_mcp/error_codes.py` from `[A-Za-z]:\\\\.*` to `[A-Za-z]:\\.*` to correctly match single backslashes in standard Windows paths (`C:\music\song.mp3`).
- Fixed POSIX path stripping regex from `/[^\\s]*` to `(?<!\S)/[^\s]+` with a negative lookbehind for non-whitespace so that slash-delimited terms like MIME types (`audio/mpeg`), URLs (`/v1/releases`), or strings (`artist/title`) are no longer incorrectly treated as paths and redacted to `[path]`.
- Mapped `SyntaxError` and `UnicodeError` to `E_PARSE_ERROR` in `_EXCEPTION_TO_CODE`.
- Added unit tests covering standard Windows paths, non-path text preservation (MIME types, URLs, artist/title), and `E_PARSE_ERROR` mapping in `tests/test_error_codes.py`.


### 2026-10-29 — Repo health follow-up (CI, lint, stale tests)

- Fixed CI matrix (`3.10` -> `3.11`) and added `fail-fast: false` so all matrix legs run.
- Fixed pylint `E0401` by correcting the relative import in `tools/musicbrainz.py`.
- Repaired stale exact-equality tests (playlist job counts, tool registry, backup path).
- Fixed release builder to strip `[tool.uv]` from bundled `pyproject.toml`.
- Ran full suite locally and verified lint passes.
- Remaining work tracked by issues #64-#70 (coverage, write-path tests, Windows matrix, conftest isolation, CI contract test).
### 2026-10-30 — Issue #70: tests/conftest.py isolation, network guard, timeouts, markers
- Added tests/conftest.py with autouse app-data isolation (MUSICBEE_TAGGER_DATA_DIR/HOME/APPDATA -> tmp_path), autouse socket/urlopen network blocker with @pytest.mark.network opt-out, and pytest_collection_modifyitems skips for windows/requires_audio_fixtures markers.
- Registered network, slow, windows, requires_audio_fixtures markers; enabled --strict-markers, --timeout=120, and -W error::DeprecationWarning:musicbee_tagger_mcp in pyproject.toml; added pytest-timeout dev dependency.
- Marked test_real_files and test_field_map_roundtrip as requires_audio_fixtures; switched test_windows_mcpb to windows marker; added tests/test_ffmpeg_available.py.
- Updated CI to assert ffmpeg and run the suite twice for determinism.

### 2026-10-30 — Issue #57: store best MusicBrainz candidate details for unresolved tracks
- complete_batch now persists best candidate metadata (recording ID, title, artist, duration, duration difference, verification reason) for unresolved/failed tracks.
- job_status exposes candidate metadata, manual override audit entries, and unresolved review helpers.
- Added manual staging override paths in job store, playlists tools, staging manager, and tag tools that require and record user justification.
- Validation: py_compile passed; CI pending.


### 2026-10-30 — Issue #57: store best MusicBrainz candidate details for unresolved tracks
- complete_batch now persists best candidate metadata for unresolved/failed tracks.
- job_status exposes candidate metadata and manual override audit entries.
- Added manual staging override paths requiring and recording user justification.
- Validation: py_compile passed; CI pending.

## 2026-10-31 - Issue #10 release-readiness gaps

- Hardened path redaction in error_codes.py (redact_paths) and applied to MCP error paths.
- Removed BOM from tests/test_acrcloud.py.
- Added audio fixture protection fixture and docs/AUDIO_FIXTURES.md.
- Documented shell-access security boundary in docs/THREAT_MODEL.md.
- Verified package import isolation (server does not import physical write modules).
- MusicBrainz User-Agent already uses public email contact.
- Retained exact expected tool-set check.

### 2026-10-31 — Issue #10 verification pass

- Verified redact_paths handles URL-decoded payloads and serialized Windows paths.
- Confirmed MCP server import isolation from physical write modules (tag_applier, tag_format_writers, apply_staged, staged_apply not imported).
- Confirmed source files are UTF-8 clean; only prior BOM removal needed.
- MusicBrainz User-Agent uses public email contact (repo is private).
- Audio fixtures remain tracked; autouse protection fixture guards against modification.
- Shell-access security boundary documented in docs/THREAT_MODEL.md.
- Retained exact expected MCP tool-set check.
- Full test suite: 171 passed, 30 skipped.

## 2026-10-31 — Issue #10 agent verification

- Re-ran full suite locally against issue-10 source: 171 passed, 30 skipped.
- Confirmed CI on PR #116 is green across Python 3.11/3.12/3.14 and Windows MCPB.
- No further code changes required; acceptance criteria already satisfied by commits 415e630 and 2c6f531.

## 2026-10-31 - Issue #10 follow-up hardening

- Strengthened redact_paths to handle URL-decoded and serialized Windows paths.
- Hardened remaining MCP error paths (ACRCloud provider errors, batch queue ValueError, batch brief filename clue extraction).
- Coerced non-string error messages to strings before redaction.
- Confirmed source files are UTF-8 without BOM; no encoding fixes needed.
- MusicBrainz User-Agent continues to use the public email contact (repository is private).
- Audio fixtures remain tracked with documented strategy and autouse protection.
- Shell-access security boundary remains documented in docs/THREAT_MODEL.md.
- Exact MCP tool-set check retained.
- Validation: py_compile passed; CI pending.

## 2026-10-31 - Issue #10 final verification

- Hardened ACRCloud provider error path to catch exceptions and redact paths.
- Re-verified redact_paths handles decoded and serialized Windows paths.
- Re-verified package builds and import isolation (server does not import physical write modules).
- Confirmed source files are UTF-8 without BOM; no encoding fixes needed.
- Confirmed MusicBrainz User-Agent uses public email contact (repository private).
- Confirmed tracked audio fixtures remain in Git with autouse protection.
- Confirmed shell-access security boundary documented in docs/THREAT_MODEL.md.
- Retained exact expected MCP tool-set check.
- Validation: full suite 171 passed, 30 skipped (CI).

## 2026-10-31 - Issue #10 follow-up hardening (agent)

- Strengthened redact_paths for URL-decoded and serialized Windows paths and recursive containers.
- Hardened registry resolution and list_staged_changes/list_jobs error paths.
- Retained exact MCP tool-set check and documented fixture/security boundaries.
- Validation: compileall passed; CI pending.


## 2026-10-31 - Issue #10 final fix

- Fixed Windows path regex in redact_paths to actually match backslash paths.
- Merged master and resolved conflicts; removed undefined audit_staged_changes tool reference.
- Verified import isolation and redact_paths behavior manually; CI blocked by billing.
- Validation: compileall and import check passed.
## 2026-10-31 - Issue #10 release-readiness follow-up (agent)

- Strengthened `redact_paths` to handle decoded payloads, serialized Windows paths, and non-string/bytes inputs.
- Hardened MCP error paths (review.py, acoustid.py, musicbrainz.py) to redact paths.
- Verified package import isolation: MCP server does not import physical write modules.
- Confirmed source files are UTF-8 clean; no encoding fixes needed.
- Confirmed MusicBrainz User-Agent uses public email contact (repository private).
- Confirmed tracked audio fixtures remain in Git with autouse protection.
- Confirmed shell-access security boundary documented in docs/THREAT_MODEL.md.
- Validation: compileall and import checks passed; CI verification pending due to billing block.
"""

## 2026-10-31 - Issue #10 final hardening (agent)

- Repaired duplicate `manual_override` parameter in `StagingManager.stage`, restoring a valid signature and docstring.
- Re-added `manual_override` parameters to `stage_tag_changes` so staging calls resolve correctly.
- Hardened `redact_paths` POSIX pattern to redact absolute paths while preserving inline API-style slash segments and serialized Windows paths.
- Redacted queue operation error strings in `operations.py`.
- Verified source compiles and exact MCP tool set remains unchanged.
- Validation: compileall passed; CI pending due to billing.

## 2026-10-31 - Issue #10 verification refresh (agent)

- Re-verified redact_paths behavior for decoded and serialized Windows paths; compileall passed.
- Confirmed exact MCP tool set and import isolation remain intact.
- CI verification remains blocked by repository billing limits; changes pushed for CI.

### 2026-10-31 — Issue #10 finalization
- Fixed pylint duplicate method/function definitions in job_store.py and tools/musicbrainz.py.
- Hardened redact_paths for bytes, None, and dict keys.
- Verified imports and pylint errors-only pass locally.


## 2026-10-31 - Issue #10 final hardening (agent)

- Re-added audit_staged_changes helper in tools/tags.py (path-safe wrapper).
- Verified exact MCP tool set now matches test_secure_pipeline (33 tools).
- Verified import isolation: server does not import physical write modules.
- Source files are UTF-8 without BOM; no encoding fixes needed.
- MusicBrainz UA uses public email contact (repo private).
- Audio fixture protection and shell-access boundary already documented.
- Validation: compileall passed; CI blocked by billing.
