# MusicBee Tagger MCP

MusicBee Tagger MCP is a local stdio MCP server for investigating and proposing
audio metadata corrections. It reads audio metadata, searches and verifies
MusicBrainz candidates, and stages proposals for review.

**The MCP server never writes audio files.** Only the separate
`musicbee-tagger-apply` CLI can apply staged changes, after interactive user
confirmation, and it creates backups by default.

## Windows desktop release

The release bundle includes a Python wheel, source distribution, Windows
installer, Claude Code MCP configuration, and Claude Code plugin archive.
The installer defaults to:

- Application and virtual environment: `K:\tools\mcp-servers\musicbee-tags\`
- Launchers: `K:\bin\`
- Private stage data: `K:\tools\mcp-servers\musicbee-tags\data\staged\`

The `data` directory is separate from the installed environment so package
upgrades do not replace pending proposals. The installer preserves existing
data. Back up the data directory to preserve pending stage manifests; no
automatic cleanup or retention is performed.

1. Download the Windows release bundle and extract it.
2. In PowerShell, run the included installer, supplying the downloaded wheel:

   ```powershell
   .\install.ps1 -WheelPath .\musicbee_tagger_mcp-0.1.0-py3-none-any.whl
   ```

   The installer creates a dedicated virtual environment, installs the wheel,
   and writes `musicbee-tagger-mcp.cmd` and `musicbee-tagger-apply.cmd`.
3. To add the standalone MCP server to Claude Code at user scope, import the
   provided `mcp-config.json` entry:

   ```powershell
   $server = (Get-Content .\mcp-config.json -Raw | ConvertFrom-Json).mcpServers.'musicbee-tagger'
   $json = $server | ConvertTo-Json -Compress -Depth 10
   claude mcp add-json --scope user musicbee-tagger $json
   claude mcp get musicbee-tagger
   ```

4. Alternatively, add the included Claude Code marketplace and install its
   plugin:

   ```powershell
   claude plugin marketplace add .\claude-marketplace
   claude plugin install musicbee-tagger@musicbee-tagger
   ```

   The plugin uses the stable `K:\bin` launcher and defaults to the same private
   data root. Restart or reload Claude Code after configuring the server.
5. Confirm the server is connected with `claude mcp list`, then use the
   registered MusicBee tools. Tokens are process-local and expire when the MCP
   server exits.

To inspect or apply pending proposals, use the user CLI launcher:

```powershell
K:\bin\musicbee-tagger-apply.cmd --list
K:\bin\musicbee-tagger-apply.cmd --all --dry-run
K:\bin\musicbee-tagger-apply.cmd --all
```

The last command prompts before each write. Review each diff carefully. Do not
run an apply command unless you intend to modify the corresponding audio file.

### Configuration and data

The standalone config sets `MUSICBEE_TAGGER_DATA_DIR` for the server process.
The generated apply launcher sets the same value, so both commands use the
same staged manifests. When invoking the CLI manually, set that environment
variable to the install's `data` directory first.

Files are read-only to the MCP process except for private stage manifests. The
server accepts paths only at file/playlist registration, then uses opaque
tokens. It does not return absolute paths in tool results. The process-local
token registry is not preserved across restarts.

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
