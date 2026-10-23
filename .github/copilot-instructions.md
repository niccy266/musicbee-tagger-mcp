# Project Guidelines

## Working with the User

- Prefer implementing clear requests over returning only a plan. Explain assumptions when they affect behavior; ask before proceeding when uncertainty materially changes scope or risk.
- Give concise progress updates at meaningful milestones. For substantive code changes, append what changed and how it was verified to the end of `WORK_LOG.md`.
- The user has authorized commits on this working branch. Commit coherent, verified changes regularly, use a clear message, and include the repository's required Copilot co-author trailer. Do not amend existing commits.
- Explain system behavior in practical terms when asked, especially how MCP tools, tokens, playlists, and MusicBrainz entities fit together.

## Privacy and Audio Safety

- Preserve the token-based design: accept paths only at `register_files` or `register_playlist`, then use opaque tokens. Never return or log absolute audio or playlist paths; sanitize failures as well as successful results.
- Treat filenames and parser output as clues, not facts. Artist/title order is ambiguous; use both candidates and corroborate with embedded tags, duration, and reliable sources.
- Keep the MCP server read-only with respect to audio files. Only stage proposed metadata after the MusicBrainz verification gate passes; never apply physical audio changes. The user reviews and applies staged changes through the CLI.
- Playlist import must resolve relative local entries against the playlist's directory, skip remote URLs and unsupported formats safely, and return useful path-free per-entry errors.

## Implementation and Verification

- Follow existing Python patterns and make focused changes. Add tests for behavior and privacy guarantees, and update directly related skill or project documentation.
- Run the smallest relevant tests first; run the full suite for cross-cutting changes. Typical command:
  `$env:PYTHONPATH='src'; .\\.venv\\Scripts\\python.exe -m pytest -q`
- If Windows denies pytest's default temporary directory, use a repository-local `--basetemp`, inspect and remove that test-only directory afterward.
- Run `git diff --check`, review the final diff, and confirm the worktree state before committing.
