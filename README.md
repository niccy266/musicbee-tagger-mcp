# MusicBee Tagger MCP

MusicBee Tagger MCP is a local stdio MCP server for investigating and proposing
audio metadata corrections. It reads audio metadata, searches and verifies
MusicBrainz candidates, and stages proposals for review.

**The MCP server never writes audio files.** It also exposes no MCP tool that
accepts playlist or audio paths. Run the local registration command yourself
in a separate PowerShell window and give the agent only its returned tokens.
Only the separate `musicbee-tagger-apply` CLI can apply staged changes, after
interactive user confirmation, and it creates backups by default.

This keeps paths out of chat and MCP request/response payloads. It is not a
Windows security boundary: an agent with unrestricted local shell access as
your Windows user could inspect the registration files. Use the cleanup command
after the investigation; use a separately isolated service account if that
stronger threat model is required.

## Windows desktop release

The release bundle includes a Python wheel, source distribution, Windows
installer, Claude Code MCP configuration, and Claude Code plugin archive with
the model-invocable `musicbee-investigator` skill.
The installer defaults to:

- Application and virtual environment: `K:\tools\mcp-servers\musicbee-tags\`
- Launchers: `K:\bin\`
- Private stage data: `K:\tools\mcp-servers\musicbee-tags\data\staged\`
- Private registration data: `K:\tools\mcp-servers\musicbee-tags\data\registered\`
- Persistent batch-operation queue: `K:\tools\mcp-servers\musicbee-tags\data\queue\`

The `data` directory is separate from the installed environment so package
upgrades do not replace pending proposals, local registrations, or the shared
batch-operation queue. The installer preserves existing data. Back up the data
directory to preserve them. Queue items persist until their status is updated;
there is no automatic cleanup.

MCP agents connected to the same configured data directory share the durable
operation queue across server restarts. Use `enqueue_batch_operation` to add
path-free work, `list_batch_operations` to query it by status or batch, and
`update_batch_operation` to record progress. Queue items remain available until
their status is updated; all agents using the same data directory see the same
queue.

To install directly from a source checkout without downloading or extracting a
release bundle, run this from the repository root:

```powershell
.\install.ps1
```

This builds a wheel from the checkout in a temporary directory and passes it
to the same installer used by the release bundle. Python 3 and the Windows
`py` launcher are required. Override the default application and launcher
directories if needed:

```powershell
.\install.ps1 -InstallRoot "D:\Apps\MusicBeeTagger" -BinRoot "D:\Tools\bin"
```

Alternatively, download and extract a Windows release bundle, then run its
installer while supplying the included wheel:

   ```powershell
   .\install.ps1 -WheelPath .\musicbee_tagger_mcp-0.4.4-py3-none-any.whl
   ```

   Before upgrading an existing installation, close MCP clients using the
   server. If installed MusicBee Tagger processes are running, the installer
   asks to close them. If a process has no closable window or does not exit, it
   offers to terminate it before continuing. Save any work in those processes
   first. The installer also removes stale `~usicbee-tagger-mcp*` pip leftovers
   from the dedicated environment after interrupted upgrades.

   The installer creates a dedicated virtual environment, installs the wheel,
   and writes `musicbee-tagger-mcp.cmd`, `musicbee-tagger-apply.cmd`,
   `musicbee-tagger-register-playlist.cmd`, and
   `musicbee-tagger-clear-registrations.cmd`.
3. To add the standalone MCP server to Claude Code at user scope, import the
   provided `mcp-config.json` entry:

   ```powershell
   $server = (Get-Content .\mcp-config.json -Raw | ConvertFrom-Json).mcpServers.'musicbee-tagger'
   $json = $server | ConvertTo-Json -Compress -Depth 10
   claude mcp add-json --scope user musicbee-tagger $json
   claude mcp get musicbee-tagger
   ```

4. Alternatively, use the persistent GitHub marketplace. This tracks the
   `release-ready-mcp` branch, so future marketplace updates fetch the branch
   rather than reading an old extracted release directory. To migrate an
   existing local marketplace with the same name, remove it first (this also
   uninstalls that marketplace's plugin), then run:

   ```powershell
   claude plugin marketplace remove musicbee-tagger
   claude plugin marketplace add niccy266/musicbee-tagger-mcp#release-ready-mcp --scope user
   claude plugin install musicbee-tagger@musicbee-tagger
   ```

   The plugin uses the stable `K:\bin` launcher and defaults to the same private
   data root. It also provides the `musicbee-investigator` skill for metadata
   investigation. Restart or reload Claude Code after configuring the server.
   Future updates come from the tracked GitHub branch:

   ```powershell
   claude plugin marketplace update musicbee-tagger
   claude plugin update musicbee-tagger@musicbee-tagger
   ```

   The bundled `.\claude-marketplace` directory remains useful for offline
   installation, but it is a snapshot: updates only see files written to that
   same directory. It does not follow future release bundles automatically.
5. Register a playlist without sending its path to the agent. Open a separate
   PowerShell window (not the agent's terminal) and run:

   ```powershell
   K:\bin\musicbee-tagger-register-playlist.cmd
   ```

   Enter the playlist path at the prompt, or pass it as a quoted argument:

   ```powershell
   K:\bin\musicbee-tagger-register-playlist.cmd "S:\Music\Playlists\Example.m3u"
   ```

   The path is handled locally by the registration command and is not sent over
   MCP. Paste only the returned tokens into your agent conversation. The
   path-to-token mappings stay in
   `K:\tools\mcp-servers\musicbee-tags\data\registered\` and persist across MCP
   restarts and Windows logins for the same user. After the investigation, run
   the cleanup command in a separate terminal and type `YES` when prompted:

   ```powershell
   K:\bin\musicbee-tagger-clear-registrations.cmd
   ```
6. Confirm the server is connected with `claude mcp list`, then use the
   registered token-only MusicBee tools.

To inspect or apply pending proposals, use the user CLI launcher:

```powershell
K:\bin\musicbee-tagger-apply.cmd --list
K:\bin\musicbee-tagger-apply.cmd --all --dry-run
K:\bin\musicbee-tagger-apply.cmd --all
```

The last command shows a fixed-position, color review table. Press Enter to
apply with a backup, `n` to mark the item failed and continue, `a` to defer it
to the end of the pending review list, or `q` to quit. Missing source files are
logged and archived from the pending list automatically. Review each diff
carefully and apply only changes you intend to write to audio.

Agents can inspect an existing proposal with `get_staged_change`, then amend it
with `amend_staged_changes` or withdraw it with `withdraw_staged_change`. These
actions update only the local stage manifest; amendment re-reads the current
tags and requires the stage revision plus a path-free reason. Withdrawn stages
remain in local history and are excluded from pending changes. Only the user
CLI applies audio tags. Filename-derived artist/title pairs are ambiguous
research clues, not evidence: a separator can split an artist name, a title,
or unrelated text, so corroborate those values before staging them.

### ACRCloud audio identification (optional)

The optional `identify_acrcloud` MCP tool uses ACRCloud credentials from the
server environment:

- `ACRCLOUD_ACCESS_KEY` (or `ACRCLOUD_KEY` / `ACR_ACCESS_KEY`)
- `ACRCLOUD_ACCESS_SECRET` (or `ACRCLOUD_SECRET` / `ACR_ACCESS_SECRET`)
- `ACRCLOUD_HOST` or `ACRCLOUD_ENDPOINT` (optional; defaults to
  `identify-<region>.acrcloud.com`)
- `ACRCLOUD_REGION` (optional; defaults to `us-west-2`)
- `ACRCLOUD_TIMEOUT` (optional; defaults to `20` seconds)

The tool returns identification evidence only. It never stages tags or writes
audio files.
The generated CLI launchers set the same value, so the MCP server, playlist
registration command, and apply CLI use the same persistent data directory.

Audio files are read-only to the MCP process except when the user applies
staged changes with the CLI. The MCP server accepts opaque tokens only. The
human-run registration command resolves the playlist locally and stores
token-to-path mappings in the private data directory. Tokens remain usable
across MCP restarts and Windows logins for the same user and install. The
separate cleanup command removes those mappings after explicit confirmation.

## Development

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q --basetemp .\.pytest-tmp
.\.venv\Scripts\python.exe scripts\build_release.py
```

The full installation and MCP reference guide is in
[`docs/index.html`](docs/index.html). The release setup is intentionally local
and single-user; it does not provide hosted/network access, automatic audio
writes, investigation archives, or confidence-based auto-staging.

## Shared batch queue

All MCP clients using the same configured data directory share a durable,
SQLite-backed queue. Agents can add path-free operations with
`enqueue_batch_operation`, query by batch and status with
`list_batch_operations`, and record progress with `update_batch_operation`.
Queue entries are retained across server restarts and package upgrades; include
no local audio or playlist paths in titles or details.

## Claude Desktop MCP Bundle

The release builder creates `dist\musicbee-tagger-mcp-0.4.4.mcpb` for Claude
Desktop on macOS and Linux, and builds
`dist\musicbee-tagger-mcp-0.4.4-windows.mcpb` on Windows. Install the
Windows-specific bundle in Claude Desktop through **Settings > Extensions >
Advanced settings > Install Extensionâ€¦**. It contains a self-contained server
executable, so Claude does not need to set up `uv`, find Python on `PATH`, or
move temporary files between drives. Build Windows release assets on Windows
with `python -m pip install -e ".[release]"` before running
`python scripts/build_release.py`. If an older MusicBee Tagger extension is
present, uninstall it before installing the new bundle.

The extension runs the MCP server locally; it does not install a separate
remote server or require an HTTPS proxy. Claude manages where the extension
files are stored; the extension's **MusicBee Tagger data directory** picker
controls the separate shared data directory used by the server. That setting
passes the selected path as `MUSICBEE_TAGGER_DATA_DIR`. The data directory defaults to
`K:\tools\mcp-servers\musicbee-tags\data`, matching this project's Windows
installer. The standalone server, when run without that environment variable,
uses `%APPDATA%\musicbee-tagger-mcp\` on Windows. The MCP server remains
path-free: register playlists using the separate human-run CLI, and use the CLI
to review and apply staged changes. Configure the CLI to use the same directory
as the extension; if you choose another directory in Claude Desktop, set that
same path when running the CLI:

```powershell
$env:MUSICBEE_TAGGER_DATA_DIR = "K:\tools\mcp-servers\musicbee-tags\data"
K:\bin\musicbee-tagger-register-playlist.cmd
```

## Artist split validation (agent-assisted)

The agent loop exposes four read-only tools for splitting malformed artist
fields: `propose_artist_split` (mechanical pass), `search_musicbrainz_artist`
(existence check), `verify_artists_on_recording` (credit evidence), and
`flag_suspicious_artists` (garble heuristics). A split is staged only when
candidates exist on MusicBrainz and the credit evidence supports it;
verified multi-artist values are staged with `; ` as separator.
