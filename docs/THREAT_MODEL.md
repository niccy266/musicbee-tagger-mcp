# Threat Model and Path-Handling Decision

> Status: decided. This documents the security decision required by issue #3
> ("registration: MCP tool or human-run CLI") and the trust boundaries the
> code implements. Read this before changing anything in `file_registry.py`,
> `tools/files.py`, `staging.py`, or `stage_manifest_store.py`.

## Deployment context

- Single user, single Windows desktop, private repository.
- The MCP server talks to one agent over stdio on the same machine.
- No network exposure: no hosted MCP, no Docker, no multi-user mode.

## Actors and trust levels

| Actor | Trust level | Can do |
|---|---|---|
| Human user | Full trust | Runs CLIs, edits audio, approves applies |
| MCP agent (e.g. Claude Code) | Untrusted for paths | Calls MCP tools with tokens only |
| Config / registry files on disk | Human-owned | Readable by anything the user can read |

## Core decision: registration is a human-run CLI, not an MCP tool

**Path-taking registration is NOT exposed as an MCP operation.** The MCP
server exposes no tool that accepts a filesystem path. Registration happens
only through `musicbee-tagger-register` (playlist CLI), which the user runs
in a separate terminal.

Rationale:

1. The user chooses which files enter the workspace; the agent cannot add
   arbitrary files by supplying paths.
2. Path-free by construction: no MCP request ever contains a path, so no
   tool error, log line, or serialization can leak one from registration.
3. An allowed-root check (canonically resolving and confining paths) is
   unnecessary for MCP because MCP never receives paths. The playlist CLI
   already rejects unsupported formats and unresolvable entries, and every
   error path returns a message without the entry path.

If registration ever becomes an MCP tool, this decision must be revisited
with an allowed-root config, `resolve()`-then-containment checks, symlink
and traversal rejection, and extension allowlisting. Do not make that change
casually.

## Attack surface and mitigations

| Concern | Status |
|---|---|
| Paths in MCP responses | Mitigated — tokens and bare display names only; `file_path` keys popped before return |
| Paths in MCP error text | Mitigated — tool handlers catch exceptions and return path-free messages; `read_audio_metadata` raises path-free errors |
| Paths in MCP logs / serialization | Mitigated — server emits only tool results; nothing path-bearing is in the response payload |
| Agent reading the registry directly | Not mitigated (accepted) — the agent runs on the same user account and holds whatever filesystem rights the user has. The registry stores absolute paths under the private data directory. A truly hostile agent with shell access is out of scope: it could read any user file regardless |
| Token guessing | Mitigated — tokens are UUIDv4, validated with strict UUID parsing before lookup |
| Token replay across restarts | By design — the persistent registry lets tokens survive restarts; the user clears registrations via the confirmation-gated clear CLI |
| Staged manifests | Accepted — `staged/*.json` contains `absolute_path` on disk so the human CLI can apply; the MCP `list_pending()` view returns path-free summaries only |
| Playlist entries escaping intent | Mitigated — only `.m3u`/`.m3u8`, audio extensions only, remote entries rejected, per-entry path-free skip reasons |
| Prompt injection via tags/filenames | Accepted — an agent could read malicious tag text; it cannot write audio without the human CLI, which prompts before applying |

## Residual risk (explicitly accepted)

- A malicious or compromised agent with unrestricted shell access can read
  the registry, the manifests, and the audio files directly. This equals the
  user's own privileges and is inherent to a local desktop agent; nothing
  short of OS-level sandboxing changes it.
- Display names (filename stems) are shown to the agent. Filenames may
  contain sensitive wording; this is intentional and required for the
  investigation workflow.

## Verification

- `tests/` covers path concealment, playlist parsing, staging summaries, and
  registry persistence, including Windows-style absolute paths.
- Adding or changing an MCP tool requires: no path parameter, no path in the
  return value, no path in any error branch, and a test proving it.
