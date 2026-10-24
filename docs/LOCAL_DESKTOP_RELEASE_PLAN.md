# Local Desktop Release Plan

> **Purpose:** Give a fresh coding agent enough context to prepare MusicBee Tagger MCP for reliable use on one Windows desktop.
>
> **Scope:** Local Python package, Claude Code-style user configuration, `K:\bin` launcher, private local state, searchable investigation logs, and conservative confidence routing.
>
> **Not in scope:** Docker, hosted/network MCP, PostgreSQL, multi-user support, or automatic writes to audio files.

---

## 1. Read This First

### Product goal

Make the MCP server easy to install and connect to Claude Code on the user's desktop, while keeping audio paths private and all physical audio edits under explicit user control.

### User preferences already gathered

- This is a **single-user desktop tool**.
- The first target client is **Claude Code**, using a user-level configuration.
- Install the Python application under:
  `K:\tools\mcp-servers\musicbee-tags\`
- Put launchers or aliases in:
  `K:\bin\`
- Prefer a **Python package** installation.
- A human-run local command accepts playlist paths; the MCP server accepts only
  opaque file tokens.
- Neither the agent nor ordinary MCP responses/logs should expose absolute paths.
- Use a configurable private state/log root, set in the user-level MCP config. The requested default is:
  `K:\tools\mcp-servers\musicbee-tags\`
- A Bash alias is acceptable if the MCP client can launch it reliably. On Windows, provide and test a native `.cmd` launcher as the dependable option.
- Investigation summaries, staged proposals, applied changes, and unresolved searches should be recorded.
- Confidence thresholds need validation against real examples and must remain configurable/tunable.

### Non-negotiable safety boundary

**Auto-stage is not auto-apply.**

- The agent may inspect, search, verify, preview, log, and stage proposals.
- The user-controlled CLI remains the only path that physically changes audio files in this plan.
- Do not add an MCP tool that applies tags.
- Any future request to let an agent apply audio changes requires a separate design and explicit approval. Do not infer that permission from confidence thresholds or logging requirements.

---

## 2. Current Project Starting Point

The repository already has:

- An MCP server using **stdio** transport.
- A Python console entry point: `musicbee-tagger-mcp`.
- A separate user CLI: `musicbee-tagger-apply`.
- Nine MCP tools for metadata inspection, MusicBrainz investigation, preview, staging, and mojibake repair; path-taking registration tools are not exposed.
- Opaque tokens backed by a persistent, local token-to-path registry in the configured private data directory. A human-run CLI registers playlists and a separate confirmation-gated CLI clears registrations.
- Metadata reads directly from audio files; metadata is not currently cached in a database.
- Pending change manifests stored as JSON files.
- A user CLI that prompts before writing tags and creates backups by default.
- Tests for playlist parsing, path concealment, tag verification, staging, and MCP tool registration.

Recent structural refactor:

- `server.py` assembles the app and starts stdio.
- MCP handlers live in `src/musicbee_tagger_mcp/tools/`.
- MusicBrainz search, verification, and shared scoring live in separate modules.
- Manifest storage, read-only preview, staged application, and format-specific writes are separated.
- The MCP server does not import the audio-write modules.

Before changing code, inspect the current branch and worktree. Do not assume the branch, line counts, or this plan's proposed module names remain unchanged.

---

## 3. Proposed Install Layout

Keep the executable environment, launcher, and application data clearly separated:

```text
K:\tools\mcp-servers\musicbee-tags\
├── .venv\                 # Dedicated Python environment
├── pyproject.toml / package installation
├── staged\                # Pending change manifests
├── applied\               # Applied manifests and audit records
├── search-retry\          # Temporary/transient failures, retryable
├── search-archive\        # Completed unresolved investigations
├── low-confidence\        # Low-priority, user-browsable archive
└── logs\                  # Path-free event log

K:\bin\
├── musicbee-tagger-mcp.cmd
└── musicbee-tagger-mcp.sh   # Optional; only if supported/tested by the client shell
```

This is a proposed organization, not a settled on-disk schema. Confirm that the configured root can be both the install parent and data root without packaging/upgrades overwriting user data. If not, keep the requested root as the parent and place package/runtime files and private data in distinct subfolders.

### Launcher requirements

- The MCP config should call a stable command in `K:\bin`, not a checkout path.
- Prefer a native `.cmd` launcher for Windows reliability.
- The launcher should invoke the dedicated environment's installed console script.
- Do not rely on the caller's current working directory.
- A `.sh` launcher is optional and must be tested with the actual Claude Code shell.
- Avoid baking credentials or user-specific secrets into launch scripts.

### Configuration requirements

- Use Claude Code's current supported user-level MCP configuration format. Verify the exact schema against current official documentation during implementation.
- Configure the server command, arguments, and the private data-root setting.
- Use the user's configured data root; default to `K:\tools\mcp-servers\musicbee-tags\`.
- Do not add a config option that causes paths to be included in logs or MCP responses.
- Document installation, config location, restart/reload behavior, and a health check.

---

## 4. Privacy and Persistence Model

### Paths

- Accept playlist paths only through a human-run local CLI, never through an MCP tool.
- Resolve playlist-relative entries inside the server.
- Use opaque tokens after registration.
- Store token-to-path mappings in the configured private registration directory for token resolution across MCP restarts; the registration cleanup CLI removes these mappings after explicit confirmation.
- This boundary keeps paths out of chat and MCP payloads, but is not protection from unrestricted same-user shell access.
- Never include absolute paths in:
  - MCP tool responses
  - agent-facing notes
  - investigation logs
  - search archives
  - exception text shown to the agent
- A bare filename/display name may be used as a human hint, but should not be treated as an identifier. Two files may share a name.
- Review CLI output separately: show enough information for the user to identify a file, but do not print directory paths by default.

### Metadata

- Continue reading tags from audio files on demand.
- Do not introduce a metadata database merely to make the initial install work.
- Consider metadata caching only after measuring a real performance issue.
- Do not assume the filesystem is the bottleneck; separate tag reads, MusicBrainz requests, manifest writes, and audio writes in any benchmark.

### Private state root

Use the configured data root for private application state. Keep separate subfolders for:

- pending stage manifests
- applied stage/audit records
- retryable search failures
- completed unresolved searches
- low-confidence investigation archive
- concise append-only event logs

Create folders with restrictive user-only permissions where supported. On Windows, document how the user's profile/ACL controls access. Do not silently fall back to a public or shared temp directory for important records.

---

## 5. Confidence Routing Proposal

The current confidence value is a **heuristic score**, not a calibrated probability. Labels such as “95%” must not be described as a measured 95% chance of correctness.

Use these initial score bands for **proposal routing only**:

### `95–100` — Auto-stage

- Automatically create a pending stage proposal.
- Log that it was auto-staged.
- Still require all verification/evidence gates below.
- **Do not write the audio file.** The user's CLI remains the apply gate.

### `85–94.9` — Corroborate, then agent judgment

- Perform web corroboration from reliable discographic sources.
- Record concise source links and why they support or contradict the candidate.
- The agent may stage only if evidence is coherent and the verifier has no important mismatch.
- Otherwise archive as unresolved.

### `75–84.9` — Stage with an explicit caution

- A proposal may be staged for user review if the verifier passes.
- Include a concise warning describing uncertainty or mismatched context.
- Do not fill album/release/year fields based only on a recording match.

### `60–74.9` — Unresolved archive

- Do not stage.
- Archive the candidate evidence for later investigation.
- Add a short reason to the path-free log.

### `<60` — Low-priority archive

- Do not stage.
- Put the unresolved investigation in a user-browsable, low-priority archive.
- This archive is a lower priority than the install, staging, and retry workflow.

### Hard gates override scores

No score band permits staging if:

- `verify_mbid` does not return `verified: true`;
- there is a material title, artist, or duration mismatch;
- required evidence is missing or contradictory;
- a match appears to be a different version (for example live vs studio) without adequate corroboration.

The exact threshold behavior, especially what evidence permits the 95+ route and what to do when MusicBrainz has no duration, must be tested and tuned before enabling auto-staging by default.

---

## 6. Logging and Search Archives

### Human-readable path-free log

Keep the ordinary log concise. Do not copy full API payloads into it.

Record:

- registration/batch summary
- auto-stage events
- stage ID and path-free proposed-field summary
- verifier score, duration difference, mismatch summary, and source links where relevant
- unresolved outcomes and archive manifest IDs
- apply attempts and outcomes
- retryable API/network failures

### Applied-stage audit

For each apply attempt, write two linked events:

1. **Before:** timestamp, event ID, stage ID, bare display name, fields proposed, and confirmation/apply intent.
2. **After:** same event ID and stage ID, outcome, fields written, backup result, and concise error reason if failed.

Write the “before” record before attempting a physical write. Write the “after” record whether the operation succeeds or fails. Do not log the absolute path.

Current behavior is user CLI apply only. Preserve that. If agent application is ever authorized later, it must use the same before/after audit and receive a separate security design.

### Search failure and unresolved records

Distinguish these outcomes:

- **Transient failure:** network error, rate limit, or service failure. Record a short reason and put a retryable manifest under `search-retry`.
- **Completed no-match:** the API responded successfully, but no candidate passed investigation. Archive at the end of the batch under `search-archive`.
- **Low-confidence candidate:** archive according to the score bands; do not mislabel it as a network failure.

The user asked for failed-search log entries to be two lines:

1. a concise failure/no-match event with reason;
2. the ID of the archived manifest.

Use a manifest ID rather than a path. The archive stays under the configured private data root.

### Minimum search manifest

Keep it small but sufficient to retry:

- manifest ID and timestamp
- path-free display name or batch-local token only if safe and meaningful
- normalized artist/title/clue inputs used for the request
- duration if available
- query variant count
- result count
- concise outcome/reason
- candidate recording IDs and scores if any were returned
- source links if web research was performed
- retry status / attempt count

Do not store audio paths, playlist paths, or raw exception messages that might include paths.

---

## 7. Delivery Phases

Complete each phase independently. Keep changes small and testable.

### Phase 0 — Confirm assumptions and baseline

- [ ] Read `.github/copilot-instructions.md`, the investigator skill, this plan, and the user guide.
- [ ] Confirm the worktree is clean and identify the target branch.
- [ ] Run the current full test suite.
- [ ] Inspect current package entry points, CLI behavior, MCP SDK version, and current Claude Code config schema.
- [ ] Confirm the install/data folder layout does not put user data inside a directory replaced by upgrades.
- [ ] Do not modify audio files during development tests.

**Exit check:** baseline tests pass and installation/config schema is documented from current official guidance.

### Phase 1 — Install package and launcher

- [ ] Create a reproducible install into the dedicated location under `K:\tools\mcp-servers\musicbee-tags\`.
- [ ] Add a native `K:\bin\musicbee-tagger-mcp.cmd` launcher.
- [ ] Add a Bash launcher only if the user's Claude Code environment requires and supports it.
- [ ] Ensure the launcher works from a different current directory.
- [ ] Verify the configured package command starts the existing stdio MCP server.
- [ ] Add a user-level Claude Code config example using the stable launcher.

**Exit check:** clean install and MCP initialize/tool-list smoke test succeed without requiring the source checkout.

### Phase 2 — Private data root and durable folders

- [ ] Read the configurable data root from user-level MCP environment/config.
- [ ] Use the requested default root unless install/data separation requires subfolders.
- [ ] Create stage, applied, retry, archive, low-confidence, and log folders on demand.
- [ ] Handle unavailable folders with explicit, path-sanitized errors; never silently lose state.
- [ ] Ensure a restart preserves pending stages and archives.

**Exit check:** state survives server restart, remains local, and no path appears in MCP responses or logs.

### Phase 3 — Structured event log and manifests

- [ ] Define versioned, append-only path-free log records.
- [ ] Log auto-stage events and link each record to a stage ID.
- [ ] Implement before/after apply events with the same event ID.
- [ ] Separate retryable transient failures from completed no-match searches.
- [ ] Archive no-match investigations at batch end, as requested.
- [ ] Make archive manifests retryable without re-registering files or requiring old tokens.
- [ ] Add safe retention/cleanup guidance; do not automatically delete user records.

**Exit check:** tests prove event pairing, path concealment, restart/retry behavior, and failure visibility.

### Phase 4 — Confidence routing

- [ ] Keep the current verifier as a hard evidence gate.
- [ ] Add an explicit, testable routing function for the proposed score bands.
- [ ] Require web corroboration for the 85–94.9 band before agent-judged staging.
- [ ] Include an uncertainty note for the 75–84.9 band.
- [ ] Archive 60–74.9 and below-60 outcomes without staging.
- [ ] Require no major mismatch even for scores at or above 95.
- [ ] Add tests for every boundary: 59.9, 60, 74.9, 75, 84.9, 85, 94.9, and 95.
- [ ] Keep the feature disabled or conservative by default until evaluated against a representative set of matches.

**Exit check:** boundary tests and a labeled evaluation set demonstrate that score routing does not bypass verification.

### Phase 5 — Documentation and release checks

- [ ] Update the user guide with install, config, launcher, data folders, logs, retry, and CLI apply instructions.
- [ ] Update the investigator skill with the finalized confidence routing and archive behavior.
- [ ] Document backup/restore and uninstall behavior without deleting user data.
- [ ] Run the full test suite, package build/install smoke test, config parse/launch smoke test, and `git diff --check`.
- [ ] Confirm MCP tool inventory is unchanged unless an explicitly reviewed feature requires a change.
- [ ] Confirm MCP imports still cannot reach the physical audio write implementation.
- [ ] Commit each coherent, tested phase; do not amend existing commits.

**Exit check:** another person can install and configure the server from the guide without opening the repository's source code.

---

## 8. Required Tests and Safety Checks

### Install and config

- [ ] Package installs into the dedicated Python environment.
- [ ] `K:\bin` launcher works from PowerShell and from the MCP client.
- [ ] MCP config validates and launches stdio.
- [ ] Failure messages are useful but do not echo absolute paths.

### Privacy

- [ ] MCP responses never return audio or playlist paths.
- [ ] Logs and search manifests never contain absolute paths.
- [ ] Pending stage manifests keep path information private and are readable only by the local apply workflow.
- [ ] Duplicate filenames do not cause stage/search records to be confused.

### Routing and logs

- [ ] Every confidence boundary is tested.
- [ ] Failed verification never stages regardless of score.
- [ ] Auto-stage emits a log record and still does not modify audio.
- [ ] Apply writes a before record and an after record, including on failure.
- [ ] Retryable errors and completed no-match outcomes are stored separately.
- [ ] Archived searches can be retried later from their path-free inputs.

### Audio safety

- [ ] MCP tool listing contains no apply/write tool.
- [ ] MCP server process does not import audio-write modules.
- [ ] Only explicit CLI confirmation performs physical tag changes.
- [ ] Tests use generated temporary audio fixtures or mocks, never the user's library.

---

## 9. New-Agent Handoff Instructions

The next agent should:

1. Read this plan, `.github/copilot-instructions.md`, `.agents/skills/musicbee-investigator/SKILL.md`, and `docs/index.html`.
2. Inspect the current branch, commit, worktree, test commands, and package entry points before editing.
3. Treat all preferences above as requirements unless explicitly marked “proposed” or “to validate.”
4. Implement only **one delivery phase at a time**.
5. Ask before changing the no-agent-audio-writes boundary.
6. Never send audio/playlist paths to a subagent. If delegating, pass path-free briefs and verify shared MCP token access first.
7. Use web research for weak or conflicting MusicBrainz matches; retain citations in the appropriate record.
8. Update `WORK_LOG.md` after substantive work and commit coherent verified changes with the required Copilot co-author trailer.
9. Report what changed, tests run, remaining risks, and any user decision needed.

---

## 10. Open Decisions to Validate During Implementation

- Does the install root double as the data root, or should state live in a child folder such as `data\` to protect it during upgrades?
- Which user-level Claude Code config format/version is installed on the target desktop?
- Should the `.sh` launcher be implemented, or is `.cmd` sufficient for the actual client?
- What test corpus is representative enough to tune heuristic confidence thresholds?
- Does “85–94.9 agent judgment” always require a web citation, or can another documented independent source count?
- How long should applied manifests, retryable failures, and low-confidence archives be retained?
- Is display-name logging acceptable for the user's privacy expectations, or should logs use only opaque IDs?
- What happens when no local duration or MusicBrainz duration is available? Recommended default: no auto-stage.
- Keep all actual audio writes user-confirmed by CLI. Any change to that rule needs an explicit, separate approval.
