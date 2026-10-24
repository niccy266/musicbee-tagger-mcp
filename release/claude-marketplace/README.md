# MusicBee Tagger Claude Code marketplace

For a persistent marketplace that receives updates from GitHub, use
`claude plugin marketplace add niccy266/musicbee-tagger-mcp#release-ready-mcp`
instead. The release-bundle marketplace described here is a local snapshot.

Install the Python package and Windows launchers using the release bundle's
`install.ps1`, then register this extracted marketplace directory:

```powershell
claude plugin marketplace add .\claude-marketplace
claude plugin install musicbee-tagger@musicbee-tagger
claude plugin list
```

The plugin is user-scoped by default. It invokes the `K:\bin` launcher and
stores pending proposals under
`K:\tools\mcp-servers\musicbee-tags\data\staged`.
