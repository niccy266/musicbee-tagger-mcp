# MusicBee Tagger MCP for Claude Code

This plugin connects Claude Code to the locally installed MusicBee Tagger MCP
server. Install the Python package and Windows launchers first using the
release's `install.ps1`; the plugin invokes `K:\bin\musicbee-tagger-mcp.cmd`.
It also bundles the model-invocable `musicbee-investigator` skill, which guides
Claude through the token-based metadata investigation workflow.

The MCP server accepts tokens, not playlist or audio paths. Register a playlist
locally in a separate PowerShell window, then give the agent only the returned
tokens:

```powershell
K:\bin\musicbee-tagger-register-playlist.cmd
```

You can also pass the path as a quoted argument:

```powershell
K:\bin\musicbee-tagger-register-playlist.cmd "S:\Music\Playlists\Example.m3u"
```

The path is handled only by the local command; do not paste it into the agent
conversation or run this command through an agent-controlled terminal.
Registrations persist in the configured private data directory across MCP
restarts. To delete saved playlist-to-file mappings after an investigation,
run `K:\bin\musicbee-tagger-clear-registrations.cmd` in a separate local
terminal and confirm the prompt; this does not alter audio files or staged
proposals.

The plugin config sets the private data root to
`K:\tools\mcp-servers\musicbee-tags\data`. Update both this plugin's
`.mcp.json` and the installer paths if you choose a different installation
location.

Install this directory as a local Claude Code plugin using the plugin manager,
or load it for a session with Claude Code's `--plugin-dir` option. Reload
plugins or restart Claude Code after installation.

To refresh an existing installation from an updated local marketplace, extract
the newer release over the marketplace directory, then run:

```powershell
claude plugin marketplace update musicbee-tagger
claude plugin update musicbee-tagger@musicbee-tagger
```

Audio files are never applied by the MCP server. It can only inspect, verify,
preview, and stage proposed metadata; use the separate CLI to review and apply
changes interactively.
