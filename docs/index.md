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
.\install.ps1 -WheelPath .\musicbee_tagger_mcp-0.4.6-py3-none-any.whl
```

Before upgrading an existing installation, close MCP clients using the
server. If installed MusicBee Tagger processes are running, the installer
asks to close them. If a process has no closable window or does not exit, it
offers to terminate it before continuing. Save any work in those processes
first. The installer also removes stale `~usicbee-tagger-mcp*` pip leftovers
from the dedicated environment after interrupted upgrades.

## Shared batch queue

All MCP clients using the same configured data directory share a durable,
SQLite-backed queue. Agents can add path-free operations with
`enqueue_batch_operation`, query by batch and status with
`list_batch_operations`, and record progress with `update_batch_operation`.
Queue entries are retained across server restarts and package upgrades; include
no local audio or playlist paths in titles or details.

## Docker Hosting & Two-Container Sandboxing

For containerized deployments, MusicBee Tagger MCP provides a secure, least-privilege Docker Compose setup (`docker-compose.yml`) utilizing a two-container architecture:

- **`musicbee-mcp`**: Runs the HTTPS MCP server with a read-only root file system, outbound network restricted to MusicBrainz/ACRCloud APIs, and the audio library mounted strictly **read-only** (`:ro`) to guarantee the MCP server and AI agent can never modify audio files.
- **`musicbee-apply`**: An isolated offline apply agent with **no network access** and read-write access to the audio library (`:rw`), responsible solely for executing review-approved stage manifests.

For full setup instructions, see [Docker Hosting Guide](DOCKER_HOSTING.md).

## Artist split validation (agent-assisted)

The agent loop exposes four read-only tools for splitting malformed artist
fields: `propose_artist_split` (mechanical pass, plus MusicBrainz credit-aware
`tag_value` and `warnings` when `recording_id` is passed), `search_musicbrainz_artist`
(existence check), `verify_artists_on_recording` (credit evidence), and
`flag_suspicious_artists` (garble heuristics). A split is staged only when
candidates exist on MusicBrainz and the credit evidence supports it;
verified multi-artist values are normalized and staged with `"; "` as separator,
while single-act names (e.g. `Earth, Wind & Fire`) remain intact.
