# Project Guidelines

## Working with the User

- Prefer implementing clear requests over returning only a plan. Explain assumptions when they affect behavior; ask before proceeding when uncertainty materially changes scope or risk.
- Honor explicit requests to use a context-isolated subagent. For playlist work, keep the playlist path in the parent session, register it there, and never pass the path or path-bearing output to the subagent. Before assigning MCP actions, verify the subagent can use the same server process/token registry; otherwise delegate path-free metadata analysis and keep token-dependent verification/staging in the parent.
- For metadata investigations, use web search to corroborate weak, conflicting, or incomplete MusicBrainz matches; use reliable discographic sources and retain links for material conclusions. Do not silently omit web research when requested or when the investigation workflow calls for it.
- Optimize batch work by reusing one MCP server/client session and one batch brief, respecting MusicBrainz rate limits, and returning compact outcome summaries instead of repeated full payloads. Do not assume the API can batch unrelated searches in one request.
- Give concise progress updates at meaningful milestones. For substantive code changes, append what changed and how it was verified to the end of `WORK_LOG.md`.
- The user has authorized commits on this working branch. Commit coherent, verified changes regularly, use a clear message, and include the repository's required Copilot co-author trailer. Do not amend existing commits.
- Explain system behavior in practical terms when asked, especially how MCP tools, tokens, playlists, and MusicBrainz entities fit together.

## Privacy and Audio Safety

- Preserve the token-based design: accept paths only at `register_files` or `register_playlist`, then use opaque tokens. Never return or log absolute audio or playlist paths; sanitize failures as well as successful results.
- Treat filenames and parser output as clues, not facts. Artist/title order is ambiguous; use both candidates and corroborate with embedded tags, duration, and reliable sources.
- Keep the MCP server read-only with respect to audio files. Only stage proposed metadata after the MusicBrainz verification gate passes; never apply physical audio changes. The user reviews and applies staged changes through the CLI.
- Playlist import must resolve relative local entries against the playlist's directory, skip remote URLs and unsupported formats safely, and return useful path-free per-entry errors.

## Implementation and Verification

- Keep the human/MCP reference guide in `docs/index.html` aligned with CLI commands and the registered MCP tools when their interfaces change.
- Follow existing Python patterns and make focused changes. Add tests for behavior and privacy guarantees, and update directly related skill or project documentation.
- Treat roughly 100 lines per Python module as a maintainability guideline, not a strict cap. Prefer cohesive modules and split by responsibility when a file grows; avoid arbitrary fragmentation or unrelated refactors.
- Run the smallest relevant tests first; run the full suite for cross-cutting changes. Typical command:
  `$env:PYTHONPATH='src'; .\\.venv\\Scripts\\python.exe -m pytest -q`
- If Windows denies pytest's default temporary directory, use a repository-local `--basetemp`, inspect and remove that test-only directory afterward.
- Run `git diff --check`, review the final diff, and confirm the worktree state before committing.
