# MusicBee Tagger MCP for Claude Code

This plugin connects Claude Code to the locally installed MusicBee Tagger MCP
server. Install the Python package and Windows launchers first using the
release's `install.ps1`; the plugin invokes `K:\bin\musicbee-tagger-mcp.cmd`.

The plugin config sets the private data root to
`K:\tools\mcp-servers\musicbee-tags\data`. Update both this plugin's
`.mcp.json` and the installer paths if you choose a different installation
location.

Install this directory as a local Claude Code plugin using the plugin manager,
or load it for a session with Claude Code's `--plugin-dir` option. Reload
plugins or restart Claude Code after installation.

Audio files are never applied by the MCP server. It can only inspect, verify,
preview, and stage proposed metadata; use the separate CLI to review and apply
changes interactively.
