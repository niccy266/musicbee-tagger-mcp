#!/usr/bin/env python3
"""OpenRouter agent loop for the MusicBee Tagger MCP tools.

Runs a model-driven loop over batches of 10 registered files. The model
receives a batch brief, decides which tools to call (search, verify, stage),
and the loop executes those calls locally and feeds results back until the
batch is done or the iteration cap is hit.

Requires: OPENROUTER_API_KEY environment variable.
Usage:
    export OPENROUTER_API_KEY=sk-or-...
    python scripts/openrouter_agent_loop.py [job_id] --model openrouter/free

Notes:
    - Playlists are registered by the MCP server; only opaque tokens reach
      the model, in batches of 10 from the playlist job.
    - Staging is safe (manifest only). Tag writes still go through
      apply_staged.py after human review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Allow running from a source checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

  # noqa: E402
from musicbee_tagger_mcp.tools.inspection import (  # noqa: E402
    extract_filename_clues,
    get_batch_brief,
    read_track_metadata,
)
from musicbee_tagger_mcp.tools.musicbrainz import (  # noqa: E402
    flag_suspicious_artists,
    propose_artist_split,
    search_canonical_release,
    search_musicbrainz_artist,
    verify_artists_on_recording,
    verify_mbid,
)
from musicbee_tagger_mcp.tools.tags import (  # noqa: E402
    amend_staged_changes,
    get_staged_change,
    list_staged_changes,
    preview_tags,
    stage_tag_changes,
    withdraw_staged_change,
)
from musicbee_tagger_mcp.tools.text import repair_mojibake  # noqa: E402
from musicbee_tagger_mcp.tools.acrcloud import identify_acrcloud  # noqa: E402
from musicbee_tagger_mcp.job_store import JobStore  # noqa: E402
from musicbee_tagger_mcp.data_paths import ensure_data_subdirectory  # noqa: E402

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
RETRYABLE_STATUS = {429, 500, 502, 503}
BATCH_SIZE = 1

_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "openrouter_agent.md"

def load_system_prompt() -> str:
    """Load the agent system prompt from the external Markdown file."""
    path = _SYSTEM_PROMPT_PATH
    if not path.is_file():
        alt = Path(__file__).resolve().parent / "prompts" / "openrouter_agent.md"
        if alt.is_file():
            path = alt
        else:
            raise FileNotFoundError(
                f"System prompt file not found: {_SYSTEM_PROMPT_PATH}"
            )
    return path.read_text(encoding="utf-8").strip()

SYSTEM_PROMPT = load_system_prompt()



_LOCAL_PATH_PATTERN = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\\/][^\s\"'<>|]+|\\\\[^\\\s]+\\[^\s\"'<>|]+)"
)


def _sanitize_log(value):
    if isinstance(value, dict):
        return {str(key): _sanitize_log(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_log(item) for item in value]
    if isinstance(value, str):
        value = _LOCAL_PATH_PATTERN.sub("(local path omitted)", value)
        if len(value) > 1000:
            value = value[:1000] + "...[truncated]"
        return value
    return value


class RunLog:
    """Append path-sanitized JSONL events to a local run log."""

    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **details) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event,
            **_sanitize_log(details),
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def debug_checkpoint(enabled: bool, label: str, run_log=None) -> bool:
    """Pause only in debug runs; return False when the operator enters q."""
    if not enabled:
        return True
    answer = input(f"\n[DEBUG] {label} [Enter=continue, q=stop]: ").strip().lower()
    proceed = answer != "q"
    if run_log:
        run_log.write("debug_checkpoint", label=label, choice="continue" if proceed else "stop")
    return proceed

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_track_metadata",
            "description": "Read existing tags and technical data for a file token.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {
                        "type": "string"
                    }
                },
                "required": [
                    "token"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_filename_clues",
            "description": "Parse artist/title clues out of the file's name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {
                        "type": "string"
                    }
                },
                "required": [
                    "token"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "repair_mojibake",
            "description": "Detect and repair mojibake/encoding damage in text. Call only when text is visibly garbled or has encoding damage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string"
                    }
                },
                "required": [
                    "text"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_canonical_release",
            "description": "Search MusicBrainz for the canonical release. Returns candidates with MBIDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artist": {
                        "type": "string"
                    },
                    "title": {
                        "type": "string"
                    },
                    "duration_seconds": {
                        "type": "integer"
                    }
                },
                "required": [
                    "artist",
                    "title"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_mbid",
            "description": "Verify a MusicBrainz candidate against the file (duration/artist/title). Only verified matches may be staged.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {
                        "type": "string"
                    },
                    "mb_recording_id": {
                        "type": "string"
                    }
                },
                "required": [
                    "token",
                    "mb_recording_id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stage_tag_changes",
            "description": "Stage corrected tags for a file (manifest only, no audio write until apply).",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {
                        "type": "string"
                    },
                    "new_tags": {
                        "type": "object",
                        "description": "Tag name -> value, e.g. {\"title\": \"...\", \"artist\": \"...\", \"album\": \"...\"}"
                    },
                    "mb_recording_id": {
                        "type": "string"
                    },
                    "mb_release_id": {
                        "type": "string"
                    },
                    "forensic_score": {
                        "type": "number"
                    },
                    "notes": {
                        "type": "string"
                    }
                },
                "required": [
                    "token",
                    "new_tags"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "withdraw_staged_change",
            "description": "Retract a staged change you own so it cannot apply; use before re-staging a corrected version.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage_id": {
                        "type": "string"
                    },
                    "expected_revision": {
                        "type": "integer"
                    },
                    "reason": {
                        "type": "string"
                    }
                },
                "required": [
                    "stage_id",
                    "expected_revision",
                    "reason"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "amend_staged_changes",
            "description": "Amend a pending staged change with corrected tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage_id": {
                        "type": "string"
                    },
                    "expected_revision": {
                        "type": "integer"
                    },
                    "new_tags": {
                        "type": "object"
                    },
                    "reason": {
                        "type": "string"
                    },
                    "remove_fields": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    }
                },
                "required": [
                    "stage_id",
                    "expected_revision",
                    "new_tags",
                    "reason"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_staged_change",
            "description": "Inspect a staged change by stage_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage_id": {
                        "type": "string"
                    }
                },
                "required": [
                    "stage_id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_staged_changes",
            "description": "List all pending staged changes.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for research clues about an artist, release, or track.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string"
                    },
                    "max_results": {
                        "type": "integer"
                    }
                },
                "required": [
                    "query"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mark_unresolved",
            "description": "Record a file as unresolved with a short reason.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {
                        "type": "string"
                    },
                    "reason": {
                        "type": "string"
                    }
                },
                "required": [
                    "token",
                    "reason"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "finish_batch",
            "description": "Call when every file in the batch is resolved.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string"
                    }
                },
                "required": [
                    "summary"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_memory",
            "description": "Read the persistent agent scratchpad/memory file.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory",
            "description": "Replace the persistent agent scratchpad/memory file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string"
                    },
                    "mode": {
                        "type": "string"
                    }
                },
                "required": [
                    "text"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "append_memory",
            "description": "Append text to the persistent agent scratchpad/memory file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string"
                    }
                },
                "required": [
                    "text"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_tracks",
            "description": "Return the last seen tracks (up to 20 by default).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "propose_artist_split",
            "description": "Mechanically split a malformed artist field into candidate artists (feat./ft./with/vs./x/semicolon markers).",
            "parameters": {
                "type": "object",
                "properties": {
                    "artist_field": {
                        "type": "string"
                    },
                    "split_ampersand": {
                        "type": "boolean"
                    },
                    "split_comma": {
                        "type": "boolean"
                    }
                },
                "required": [
                    "artist_field"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_musicbrainz_artist",
            "description": "Confirm a candidate artist exists as a MusicBrainz artist entity. An empty result means the name is unknown \u2014 treat the split as suspect.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string"
                    },
                    "limit": {
                        "type": "integer"
                    }
                },
                "required": [
                    "name"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_artists_on_recording",
            "description": "Check each candidate artist is actually credited on the MusicBrainz recording. Evidence, not proof \u2014 weigh partial matches against known collaborations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recording_id": {
                        "type": "string"
                    },
                    "candidate_artists": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    }
                },
                "required": [
                    "recording_id",
                    "candidate_artists"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "flag_suspicious_artists",
            "description": "Heuristic garble/debris flags (short tokens, mojibake, casing anomalies) for candidate artists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_artists": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    }
                },
                "required": [
                    "candidate_artists"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "identify_acrcloud",
            "description": "Identify a registered track using ACRCloud audio fingerprinting (opt-in fallback). Returns identification evidence only; never stages tags.",
            "parameters": {
                "type": "object",
                "properties": {"token": {"type": "string"}},
                "required": ["token"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tools",
            "description": "List all tools available to the agent.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_all_tools",
            "description": "List all tools available to the agent.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

def _search_canonical_release(artist, title, duration_seconds=None):
    return search_canonical_release(
        artist=artist, title=title, duration_sec=duration_seconds
    )


def _verify_mbid(token, mb_recording_id, forensic_score=None, **kwargs):
    metadata = read_track_metadata(token)
    if "error" in metadata:
        return metadata
    tags = metadata.get("tags", {})
    return verify_mbid(
        recording_id=mb_recording_id,
        expected_artist=tags.get("artist"),
        expected_title=tags.get("title"),
        duration_sec=metadata.get("duration_seconds"),
        forensic_score=forensic_score,
        **kwargs,
    )


MEMORY_PATH = Path("agent_memory.txt")
AGENT_MEMORY_PATH = MEMORY_PATH
memory_path = MEMORY_PATH


def default_memory_path() -> Path:
    """Return the persistent agent memory path in the private data directory."""
    return ensure_data_subdirectory("agent_memory") / "agent_memory.txt"


def _resolve_memory_path(path=None):
    if path is None:
        return default_memory_path()
    return Path(path)


def memory_file_metadata(path=None):
    """Return non-secret metadata and a content hash for staleness checks."""
    target = _resolve_memory_path(path)
    try:
        stat = target.stat()
    except FileNotFoundError:
        return {
            "path": str(target),
            "exists": False,
            "size": 0,
            "mtime": None,
            "sha256": None,
        }
    except OSError as error:
        return {
            "path": str(target),
            "exists": False,
            "size": 0,
            "mtime": None,
            "sha256": None,
            "error": f"{type(error).__name__}: {str(error)[:300]}",
        }
    digest = hashlib.sha256()
    try:
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError as error:
        return {
            "path": str(target),
            "exists": False,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "sha256": None,
            "error": f"{type(error).__name__}: {str(error)[:300]}",
        }
    return {
        "path": str(target),
        "exists": True,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "sha256": digest.hexdigest(),
    }


def read_memory(path=None):
    target = _resolve_memory_path(path)
    try:
        return target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as error:
        return f"Error reading memory: {error}"


def read_memory_with_metadata(path=None):
    metadata = memory_file_metadata(path)
    text = read_memory(path=path)
    metadata["text"] = text
    return metadata


def memory_is_stale(state=None, path=None):
    """Compare a state memory snapshot with the current memory file."""
    state = state or {}
    metadata = memory_file_metadata(path)
    if not metadata.get("exists"):
        return bool(state.get("memory"))
    if state.get("memory_path") not in (None, metadata["path"]):
        return True
    if state.get("memory_mtime") not in (None, metadata["mtime"]):
        return True
    if state.get("memory_sha256") not in (None, metadata["sha256"]):
        return True
    return False


def _atomic_write_text(target, content):
    """Write text atomically to avoid partial memory files."""
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, target)


def write_memory(text, mode="replace", path=None):
    target = _resolve_memory_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        content = str(text)
        if mode == "append":
            existing = ""
            try:
                existing = target.read_text(encoding="utf-8")
            except FileNotFoundError:
                existing = ""
            new_content = existing + content
            if content and not content.endswith("\n"):
                new_content += "\n"
            _atomic_write_text(target, new_content)
        else:
            _atomic_write_text(target, content)
        return {"status": "ok", "path": str(target), "mode": mode}
    except OSError as error:
        return {"error": f"{type(error).__name__}: {str(error)[:300]}"}


def append_memory(text, path=None):
    return write_memory(text, mode="append", path=path)


# Public aliases for alternate memory tool names.
memory_read = read_memory
memory_write = write_memory
memory_append = append_memory
memory_metadata = memory_file_metadata
memory_is_stale_check = memory_is_stale
default_memory_path_alias = default_memory_path
read_memory_with_metadata_alias = read_memory_with_metadata
RECENT_TRACKS = []
SEEN_TRACKS = RECENT_TRACKS


def get_recent_tracks(limit=20, tracks=None):
    source = tracks if tracks is not None else RECENT_TRACKS
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    if limit <= 0:
        limit = 20
    return list(source)[-limit:]


# Public aliases.
list_recent_tracks = get_recent_tracks
recent_tracks = get_recent_tracks
get_seen_tracks = get_recent_tracks
def _web_search(query: str, max_results: int = 5) -> dict:
    """Best-effort web search using DuckDuckGo's HTML endpoint."""
    import html
    import re
    import urllib.parse
    import urllib.request

    query = (query or "").strip()
    if not query:
        return {"error": "query is required"}
    if max_results < 1:
        max_results = 5
    url = "https://html.duckduckgo.com/html/"
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    try:
        request = urllib.request.Request(
            url,
            data=data,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MusicBeeTagger/1.0)"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
    except Exception as error:
        return {"error": f"web search failed: {type(error).__name__}: {error}"}

    results = []
    # Result blocks contain a result__a link and result__snippet.
    for match in re.finditer(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        body,
        re.S,
    ):
        href, title, snippet = match.groups()
        # DuckDuckGo wraps URLs in a redirect; unwrap uddg param when present.
        parsed = urllib.parse.urlparse(href)
        params = urllib.parse.parse_qs(parsed.query)
        if "uddg" in params:
            href = params["uddg"][0]
        title = re.sub(r"<[^>]+>", "", html.unescape(title)).strip()
        snippet = re.sub(r"<[^>]+>", "", html.unescape(snippet)).strip()
        if title or href:
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= max_results:
            break
    return {"query": query, "results": results}


def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web for research clues about an artist, release, or track."""
    return _web_search(query, max_results)


class _ToolNameList(list):
    """List of tool names that also supports dict-style access."""

    def __getitem__(self, key):
        if key == "tools":
            return self
        return super().__getitem__(key)


def list_tools():
    """Return the names of all tools available to the agent."""
    names = sorted(
        {
            entry.get("function", {}).get("name")
            for entry in TOOLS
            if entry.get("function", {}).get("name")
        }
    )
    return _ToolNameList(names)


list_all_tools = list_tools


def _identify_acrcloud(token):
    return identify_acrcloud(token)


list_recent_tracks = get_recent_tracks
recent_tracks = get_recent_tracks
get_seen_tracks = get_recent_tracks

LOCAL_TOOLS = {
    "read_memory": lambda: read_memory(),
    "write_memory": lambda text="", mode="replace": write_memory(text, mode=mode),
    "append_memory": lambda text="": append_memory(text),
    "memory_read": lambda: read_memory(),
    "memory_write": lambda text="", mode="replace": write_memory(text, mode=mode),
    "memory_append": lambda text="": append_memory(text),
    "get_recent_tracks": lambda limit=20: get_recent_tracks(limit),
    "list_recent_tracks": lambda limit=20: list_recent_tracks(limit),
    "recent_tracks": lambda limit=20: recent_tracks(limit),
    "get_seen_tracks": lambda limit=20: get_seen_tracks(limit),
    "read_track_metadata": lambda token: read_track_metadata(token),
    "extract_filename_clues": lambda token: extract_filename_clues(token),
    "repair_mojibake": lambda text: repair_mojibake(text),
    "search_canonical_release": _search_canonical_release,
    "verify_mbid": _verify_mbid,
    "stage_tag_changes": stage_tag_changes,
    "amend_staged_changes": amend_staged_changes,
    "withdraw_staged_change": withdraw_staged_change,
    "get_staged_change": get_staged_change,
    "list_staged_changes": lambda: list_staged_changes(),
    "web_search": lambda query, max_results=5: web_search(query, max_results),
    "identify_acrcloud": lambda token: _identify_acrcloud(token),
    "list_tools": lambda: list_tools(),
    "list_all_tools": lambda: list_all_tools(),
}


def call_openrouter(messages, model, api_key, temperature=0.2, retries=3,
                   run_log=None, stream=True, tools=None):
    """One chat completion with tool support, via the openai SDK pointed at
    OpenRouter (https://openrouter.ai/docs/quickstart#using-the-client-sdks).
    Returns the raw OpenAI-shaped dict the batch loop expects.

    ``tools`` defaults to the global ``TOOLS`` list. Pass an empty list (or
    ``False``) to make a plain text completion with no tool support, which is
    used by the separate context-compaction call.
    """
    from openai import APIStatusError, APITimeoutError, OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE,
        timeout=120,
        default_headers={
            "HTTP-Referer": "https://github.com/niccy266/musicbee-tagger-mcp",
            "X-Title": "musicbee-tagger-agent",
        },
    )
    for attempt in range(retries):
        started = time.monotonic()
        if run_log:
            run_log.write("model_request_started", model=model, attempt=attempt + 1)
        try:
            if stream:
                response_stream = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=(TOOLS if tools is None else ([] if tools is False else tools)),
                    temperature=temperature,
                    stream=True,
                    parallel_tool_calls=False,
                    stream_options={"include_usage": True},
                )
                content_parts = []
                reasoning_parts = []
                tool_call_parts = {}
                finish_reason = None
                usage = None
                printed_prefix = False
                printed_reasoning_prefix = False
                chunk_count = 0
                for chunk in response_stream:
                    chunk_count += 1
                    if getattr(chunk, "usage", None) is not None:
                        try:
                            usage = chunk.usage.model_dump(mode="json")
                        except Exception:
                            usage = str(chunk.usage)
                    for choice in (chunk.choices or []):
                        finish_reason = choice.finish_reason or finish_reason
                        delta = choice.delta
                        reasoning_delta = (
                            getattr(delta, "reasoning", None)
                            or getattr(delta, "reasoning_content", None)
                        )
                        if reasoning_delta:
                            if not printed_reasoning_prefix:
                                print("[reasoning] ", end="", flush=True)
                                printed_reasoning_prefix = True
                            reasoning_parts.append(reasoning_delta)
                            print(reasoning_delta, end="", flush=True)
                        if getattr(delta, "content", None):
                            if not printed_prefix:
                                if printed_reasoning_prefix:
                                    print(flush=True)
                                print("[assistant] ", end="", flush=True)
                                printed_prefix = True
                            content_parts.append(delta.content)
                            print(delta.content, end="", flush=True)
                        if getattr(delta, "tool_calls", None):
                            for tc in delta.tool_calls:
                                idx = getattr(tc, "index", 0) or 0
                                entry = tool_call_parts.setdefault(
                                    idx,
                                    {
                                        "id": None,
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    },
                                )
                                if getattr(tc, "id", None):
                                    entry["id"] = tc.id
                                function = getattr(tc, "function", None)
                                if function is not None:
                                    if getattr(function, "name", None):
                                        entry["function"]["name"] += function.name
                                    if getattr(function, "arguments", None):
                                        entry["function"]["arguments"] += function.arguments
                if run_log:
                    run_log.write(
                        "model_stream_completed",
                        model=model,
                        attempt=attempt + 1,
                        chunks=chunk_count,
                        elapsed_seconds=round(time.monotonic() - started, 3),
                    )
                if printed_reasoning_prefix:
                    print(flush=True)
                if printed_prefix:
                    print(flush=True)
                tool_calls = [tool_call_parts[idx] for idx in sorted(tool_call_parts)]
                message = {
                    "role": "assistant",
                    "content": "".join(content_parts) or None,
                }
                reasoning_text = "".join(reasoning_parts).strip()
                if reasoning_text:
                    message["reasoning"] = reasoning_text
                if tool_calls:
                    message["tool_calls"] = tool_calls
                    tool_summary = []
                    for tc in tool_calls:
                        try:
                            args = json.loads(tc["function"].get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        tool_summary.append(
                            tc["function"]["name"]
                            + "("
                            + ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3])
                            + ")"
                        )
                    print("  -> tools: " + ", ".join(tool_summary), flush=True)
                payload = {
                    "choices": [{"message": message, "finish_reason": finish_reason}],
                    "usage": usage,
                }
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=(TOOLS if tools is None else ([] if tools is False else tools)),
                    temperature=temperature,
                    parallel_tool_calls=False,
                )
                payload = response.model_dump(mode="json")
                choice = (payload.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                reasoning_text = (
                    message.get("reasoning")
                    or message.get("reasoning_content")
                    or ""
                ).strip()
                if reasoning_text:
                    print(f"[reasoning] {reasoning_text}", flush=True)
                visible = (message.get("content") or "").strip()
                if visible:
                    print(f"[assistant] {visible}", flush=True)
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    tool_summary = []
                    for tc in tool_calls:
                        try:
                            args = json.loads(tc.get("function", {}).get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        tool_summary.append(
                            tc.get("function", {}).get("name", "?")
                            + "("
                            + ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3])
                            + ")"
                        )
                    print("  -> tools: " + ", ".join(tool_summary), flush=True)
                if reasoning_text:
                    message["reasoning"] = reasoning_text

            choice = (payload.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            if run_log:
                run_log.write(
                    "model_response",
                    model=model,
                    attempt=attempt + 1,
                    elapsed_seconds=round(time.monotonic() - started, 3),
                    finish_reason=choice.get("finish_reason"),
                    visible_summary=message.get("content"),
                    tool_calls=message.get("tool_calls", []),
                    usage=payload.get("usage"),
                )
            return payload
        except (APITimeoutError, APIStatusError) as error:
            status = getattr(error, "status_code", None)
            retryable = status in RETRYABLE_STATUS or status is None
            if run_log:
                run_log.write(
                    "model_request_error",
                    model=model,
                    attempt=attempt + 1,
                    elapsed_seconds=round(time.monotonic() - started, 3),
                    status=status,
                    retrying=retryable and attempt < retries - 1,
                    error=str(error)[:500],
                )
            if retryable and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            detail = str(error)[:300]
            raise RuntimeError(f"OpenRouter error {status or 'timeout'}: {detail}")
        except Exception as error:
            if run_log:
                run_log.write(
                    "model_request_unexpected_error",
                    model=model,
                    attempt=attempt + 1,
                    elapsed_seconds=round(time.monotonic() - started, 3),
                    error=str(error)[:500],
                )
            raise

    raise RuntimeError("OpenRouter unreachable")


def _clean_genre_value(value):
    """Remove obvious junk/private/encoding-damage items from a genre string."""
    if not value:
        return ""
    junk_patterns = (
        "djcjnr", "added/", "private/", "isrc", "#",
    )
    items = []
    seen = set()
    for part in str(value).split(";"):
        item = part.strip()
        if not item:
            continue
        lowered = item.lower()
        if any(pattern in lowered for pattern in junk_patterns):
            continue
        if item in seen:
            continue
        seen.add(item)
        items.append(item)
    return "; ".join(items)


def _first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _as_track_name_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    try:
        result = []
        for item in value:
            if item is None:
                continue
            result.append(str(item))
        return result
    except TypeError:
        return [str(value)]


def _deduplicate_thought(text):
    text = text or ""
    # Strip any embedded copy of the system prompt so it is not duplicated in
    # the carried-forward thought window.
    text = text.replace(SYSTEM_PROMPT, "")
    lines = text.splitlines()
    deduplicated = []
    for line in lines:
        stripped = line.strip()
        if stripped and deduplicated and deduplicated[-1].strip() == stripped:
            continue
        deduplicated.append(line)
    return "\n".join(deduplicated).strip()
def _trim_to_tokens(text, max_tokens):
    text = text or ""
    if not max_tokens or max_tokens <= 0:
        return text
    # A conservative character approximation for mixed English/code text.
    max_chars = int(max_tokens) * 4
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def estimate_tokens(text):
    return max(1, (len(text or "") + 3) // 4)


def extract_agent_thought(messages):
    """Extract visible assistant reasoning and tool activity from a message history.

    System prompts, user batch briefs, and message envelope metadata are omitted
    so the result can be carried between batches without duplicating them.
    """
    chunks = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role in ("system", "user"):
            continue
        if role == "assistant":
            reasoning = message.get("reasoning") or message.get("reasoning_content")
            if reasoning:
                chunks.append("assistant_reasoning: " + str(reasoning).strip())
            content = message.get("content")
            if content:
                chunks.append("assistant: " + str(content).strip())
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                name = function.get("name", "")
                arguments = function.get("arguments", "")
                chunks.append(f"assistant_tool_call: {name}({arguments})")
        elif role == "tool":
            content = message.get("content")
            if content is not None:
                chunks.append("tool_result: " + str(content).strip())
    return "\n".join(chunks)


def build_context_block(prior_context="", lookahead=None, previous_tracks=None,
                        prior_tracks=None, previous_track_names=None,
                        future_tracks=None, upcoming_tracks=None,
                        future_track_names=None, agent_thought=None,
                        thought=None, prior_thought=None, thought_context=None,
                        memory=None, memory_context=None, agent_memory=None,
                        scratchpad=None, notes=None,
                        max_thought_tokens=10000, thought_tokens=None,
                        thought_token_budget=None, **kwargs):
    """Build the deduplicated context block injected into a batch user message."""
    if previous_tracks is None:
        previous_tracks = _first_not_none(
            prior_tracks, previous_track_names, kwargs.get("previous"),
            kwargs.get("prior_track_names"),
        )
    if future_tracks is None:
        future_tracks = _first_not_none(
            upcoming_tracks, future_track_names, kwargs.get("future"),
            kwargs.get("upcoming"), kwargs.get("lookahead_tracks"),
        )
    if agent_thought is None:
        agent_thought = _first_not_none(
            thought, prior_thought, thought_context,
            kwargs.get("thought"), kwargs.get("prior_thought"),
            kwargs.get("agent_thought_context"),
        )
    if memory is None:
        memory = _first_not_none(
            memory_context, agent_memory, scratchpad, notes,
            kwargs.get("memory"), kwargs.get("memory_context"),
            kwargs.get("agent_memory"), kwargs.get("scratchpad"),
            kwargs.get("notes"),
        )
    if thought_tokens is not None:
        max_thought_tokens = thought_tokens
    if thought_token_budget is not None:
        max_thought_tokens = thought_token_budget
    if kwargs.get("max_thought_tokens") is not None:
        max_thought_tokens = kwargs["max_thought_tokens"]

    previous_names = _as_track_name_list(previous_tracks)
    future_names = _as_track_name_list(future_tracks)
    if not future_names and lookahead:
        future_names = _as_track_name_list(lookahead)

    sections = []
    if previous_names:
        sections.append(
            "Previously processed tracks (use for album/series and release consistency):\n"
            + "\n".join(f"- {name}" for name in previous_names)
        )
    if prior_context and str(prior_context).strip():
        sections.append(
            "Prior context from earlier batches (compressed plaintext):\n"
            + str(prior_context).strip()
        )
    if future_names:
        sections.append(
            "Upcoming files not in this batch (look-ahead; use for album/series detection):\n"
            + "\n".join(f"- {name}" for name in future_names)
        )
    if memory:
        memory_text = str(memory).strip()
        if memory_text:
            sections.append("Agent memory / scratchpad:\n" + memory_text)
    if agent_thought:
        deduplicated = _deduplicate_thought(str(agent_thought))
        trimmed = _trim_to_tokens(deduplicated, max_thought_tokens)
        if trimmed.strip():
            sections.append(
                f"Recent agent thought (up to {max_thought_tokens} tokens; "
                "system prompt and message metadata stripped):\n"
                + trimmed
            )
    return "\n\n".join(sections)


def _remove_failed_output(context, failed=None, failed_names=None, **kwargs):
    """Remove failed/unresolved output lines from a context string."""
    failed = set(failed or failed_names or kwargs.get("failed_files") or [])
    text = str(context or "").strip()
    if not text:
        return ""
    failed_strs = {str(item).strip() for item in failed if str(item).strip()}
    lines = text.splitlines()
    kept = []
    for line in lines:
        is_failed = False
        for ident in failed_strs:
            if ident and ident in line:
                is_failed = True
                break
        if not is_failed:
            kept.append(line)
    return "\n".join(kept).strip()


def compact_context(prior_context="", context="", failed=None, failed_names=None,
                    failed_files=None, max_chars=None, max_context_chars=None,
                    model=None, api_key=None, use_openrouter=None, openrouter=None,
                    **kwargs):
    """Compact prior context by removing failed output and trimming to budget."""
    if use_openrouter is True or openrouter is True or model is not None or api_key is not None or kwargs.get("use_openrouter") or kwargs.get("openrouter"):
        kwargs = dict(kwargs)
        kwargs.pop("use_openrouter", None)
        kwargs.pop("openrouter", None)
        return compact_context_with_openrouter(
            prior_context=prior_context, context=context, failed=failed,
            failed_names=failed_names, failed_files=failed_files,
            max_chars=max_chars, max_context_chars=max_context_chars,
            model=model, api_key=api_key, **kwargs)

    text = str(prior_context if prior_context is not None else context or "").strip()
    if not text:
        return ""
    failed_set = set(failed or failed_names or failed_files or kwargs.get("failed") or [])
    if kwargs.get("unresolved"):
        failed_set.update(kwargs["unresolved"])
    if kwargs.get("failed_by_file"):
        failed_set.update(kwargs["failed_by_file"])
    compacted = _remove_failed_output(text, failed=failed_set)
    # Collapse repeated identical context lines while preserving order.
    unique_lines = []
    seen_lines = set()
    for line in compacted.splitlines():
        if line in seen_lines:
            continue
        seen_lines.add(line)
        unique_lines.append(line)
    compacted = "\n".join(unique_lines).strip()
    budget = max_chars if max_chars is not None else max_context_chars
    if budget is None:
        budget = kwargs.get("context_chars")
    if budget is not None:
        try:
            budget = int(budget)
        except (TypeError, ValueError):
            budget = None
    if budget and len(compacted) > budget:
        # Keep the tail, but avoid starting in the middle of a line.
        tail = compacted[-budget:]
        newline = tail.find("\n")
        if 0 < newline < len(tail) - 1:
            tail = tail[newline + 1:]
        compacted = tail
    return compacted.strip()


def compact_prior_context(*args, **kwargs):
    return compact_context(*args, **kwargs)


def review_scratchpad(memory="", scratchpad=None, notes=None, text=None,
                     max_lines=None, max_chars=None, **kwargs):
    """Scan scratchpad items and return important ones, ordered by importance."""
    source = memory if memory is not None else scratchpad
    if source is None:
        source = notes if notes is not None else text
    if source is None:
        source = kwargs.get("memory") or kwargs.get("scratchpad") or ""
    text_value = str(source or "").strip()
    if not text_value:
        return ""
    lines = text_value.splitlines()
    scored = []
    important_keywords = {
        "important", "critical", "album", "artist", "genre", "release",
        "verified", "canonical", "note", "finding", "issue", "error",
        "success", "staged",
    }
    seen = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        score = min(len(stripped), 200)
        lower = stripped.lower()
        if any(kw in lower for kw in important_keywords):
            score += 100
        if stripped.startswith(("-", "*", "#", ">")):
            score += 25
        # Prefer recent-looking timestamped entries when present.
        if stripped.startswith("[") and "]" in stripped[:40]:
            score += 50
        scored.append((score, stripped))
    if not scored:
        return ""
    scored.sort(key=lambda item: (-item[0], item[1]))
    if max_lines is not None:
        try:
            max_lines = int(max_lines)
        except (TypeError, ValueError):
            max_lines = None
    if max_lines and max_lines > 0:
        scored = scored[:max_lines]
    result = "\n".join(item[1] for item in scored).strip()
    if max_chars is not None:
        try:
            max_chars = int(max_chars)
        except (TypeError, ValueError):
            max_chars = None
    if max_chars and len(result) > max_chars:
        result = result[:max_chars].rstrip()
    return result


def scan_scratchpad(*args, **kwargs):
    return review_scratchpad(*args, **kwargs)


def review_memory(*args, **kwargs):
    return review_scratchpad(*args, **kwargs)


def scan_memory(*args, **kwargs):
    return review_scratchpad(*args, **kwargs)


def review_memory_items(*args, **kwargs):
    return review_scratchpad(*args, **kwargs)


def remove_failed_output(*args, **kwargs):
    return _remove_failed_output(*args, **kwargs)


# Public aliases for tests and callers that use alternate helper names.
build_context = build_context_block
assemble_context = build_context_block
make_context = build_context_block
assemble_context_block = build_context_block
trim_to_tokens = _trim_to_tokens
trim_thought = _trim_to_tokens
trim_agent_thought = _trim_to_tokens
deduplicate_agent_thought = _deduplicate_thought
deduplicate_thought = _deduplicate_thought
trim_thought = _trim_to_tokens
trim_agent_thought = _trim_to_tokens
build_context_text = build_context_block


def remove_last_prompt(messages=None, *args, **kwargs):
    """Remove the last user prompt from a message history/context window."""
    if messages is None:
        messages = _first_not_none(
            kwargs.get("messages"), kwargs.get("history"),
            kwargs.get("context"), (args[0] if args else None),
        )
    result = [dict(item) if isinstance(item, dict) else item for item in (messages or [])]
    for index in range(len(result) - 1, -1, -1):
        item = result[index]
        if isinstance(item, dict) and item.get("role") == "user":
            del result[index]
            break
    return result


def remove_last_user_prompt(*args, **kwargs):
    return remove_last_prompt(*args, **kwargs)


def drop_last_prompt(*args, **kwargs):
    return remove_last_prompt(*args, **kwargs)


def pop_last_prompt(*args, **kwargs):
    return remove_last_prompt(*args, **kwargs)


def limit_initial_context(context="", *args, **kwargs):
    """Limit initial context to a compact, bounded form."""
    max_chars = _first_not_none(
        kwargs.get("max_chars"), kwargs.get("max_context_chars"),
        kwargs.get("context_chars"),
    )
    if max_chars is None and args:
        for value in reversed(args):
            if isinstance(value, int):
                max_chars = value
                break
    filtered = {
        key: value for key, value in kwargs.items()
        if key not in {"max_chars", "max_context_chars", "context_chars"}
    }
    return compact_context(context, max_chars=max_chars, **filtered)


def write_successes_to_memory(successes=None, staged=None, *args, **kwargs):
    """Persist successfully staged items to the agent memory/scratchpad."""
    items = successes if successes is not None else staged
    if items is None:
        items = _first_not_none(
            kwargs.get("successes"), kwargs.get("staged"),
            kwargs.get("items"), kwargs.get("tokens"),
        )
    items = list(items or [])
    path = kwargs.get("path")
    if not items:
        return read_memory(path=path)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = read_memory(path=path)
    existing_lines = set(existing.splitlines())
    new_lines = []
    for item in items:
        item_text = str(item)
        if any(f"Success: {item_text}" in existing_line for existing_line in existing_lines):
            continue
        line = f"[{timestamp}] Success: {item_text}"
        if line not in existing_lines:
            new_lines.append(line)
            existing_lines.add(line)
    if not new_lines:
        return existing
    return append_memory("\n".join(new_lines) + "\n", path=path)


def record_successes_to_memory(*args, **kwargs):
    return write_successes_to_memory(*args, **kwargs)


def save_successes_to_memory(*args, **kwargs):
    return write_successes_to_memory(*args, **kwargs)


def expose_tool_paths(*args, **kwargs):
    """Expose all available tool names/paths for agent discovery."""
    return list_tools()


def list_tool_paths(*args, **kwargs):
    return expose_tool_paths(*args, **kwargs)


def tool_paths(*args, **kwargs):
    return expose_tool_paths(*args, **kwargs)


def compact_messages(messages=None, max_chars=None, *args, **kwargs):
    """Compact a message history into a bounded text form."""
    if messages is None:
        messages = _first_not_none(kwargs.get("messages"), kwargs.get("history"), [])
    text = "\n".join(
        str(item.get("content", "") if isinstance(item, dict) else item)
        for item in (messages or [])
    )
    return compact_context(text, max_chars=max_chars, **kwargs)


def recover_from_loop(messages=None, staged=None, *args, **kwargs):
    """Remove last prompt, compact, write successes, and prepare a retry prompt."""
    cleaned = remove_last_prompt(messages, *args, **kwargs)
    if staged:
        write_successes_to_memory(staged=staged, path=kwargs.get("path"))
    cleaned.append({
        "role": "user",
        "content": "Repeated response detected. Compact context, write successes to memory, and try a different action.",
    })
    return cleaned

def run_batch(tokens, model, api_key, max_turns, state, state_path,
              run_log=None, debug=False, prior_context="", lookahead=None,
              previous_tracks=None, prior_tracks=None, previous_track_names=None,
              future_tracks=None, upcoming_tracks=None, future_track_names=None,
              agent_thought=None, thought=None, prior_thought=None,
              thought_context=None, memory=None, memory_context=None,
              agent_memory=None, scratchpad=None, notes=None,
              max_thought_tokens=10000,
              thought_tokens=None, thought_token_budget=None, **kwargs):
    """One agent loop over one batch of tokens. Returns the message history."""
    # Accept a few natural aliases for callers and tests.
    if previous_tracks is None:
        previous_tracks = _first_not_none(
            prior_tracks, previous_track_names, kwargs.get("previous"),
            kwargs.get("prior_track_names"),
        )
    if future_tracks is None:
        future_tracks = _first_not_none(
            upcoming_tracks, future_track_names, kwargs.get("future"),
            kwargs.get("upcoming"), kwargs.get("lookahead_tracks"),
        )
    if agent_thought is None:
        agent_thought = _first_not_none(
            thought, prior_thought, thought_context,
            kwargs.get("thought"), kwargs.get("prior_thought"),
            kwargs.get("agent_thought_context"),
        )
    if thought_tokens is not None:
        max_thought_tokens = thought_tokens
    if thought_token_budget is not None:
        max_thought_tokens = thought_token_budget
    if kwargs.get("max_thought_tokens") is not None:
        max_thought_tokens = kwargs["max_thought_tokens"]

    if memory is None:
        memory = _first_not_none(
            memory_context, agent_memory, scratchpad, notes,
            kwargs.get("memory"), kwargs.get("memory_context"),
            kwargs.get("agent_memory"), kwargs.get("scratchpad"),
            kwargs.get("notes"),
        )
    if memory is None:
        memory = read_memory()

    previous_track_names = _as_track_name_list(previous_tracks)
    future_track_names = _as_track_name_list(future_tracks)
    if not future_track_names and lookahead:
        future_track_names = _as_track_name_list(lookahead)
    # Give the model short, 6-character aliases for opaque track tokens so it
    # does not have to reproduce long UUIDs.  Internal state, staging, and job
    # tracking continue to use the full tokens.
    token_aliases = {}
    short_to_full = {}
    for token in tokens or []:
        if not isinstance(token, str):
            continue
        alias = token[:6]
        if alias in short_to_full and short_to_full[alias] != token:
            for start in range(1, max(1, len(token) - 5)):
                candidate = token[start:start + 6]
                if len(candidate) == 6 and candidate not in short_to_full:
                    alias = candidate
                    break
        token_aliases[token] = alias
        short_to_full[alias] = token

    reported_failed = set(state.get("unresolved", []) or [])
    reported_failed.update(state.get("errors", {}) or {})
    if tokens and all(token in reported_failed for token in tokens):
        state.setdefault("staged", [])
        state.setdefault("unresolved", [])
        state["unresolved"] = list(dict.fromkeys(list(state.get("unresolved", [])) + list(tokens)))
        state.setdefault("errors", {})
        for token in tokens:
            state["errors"].setdefault(token, "Reported as failed in a previous batch")
        state["finished"] = True
        save_state(state_path, state)
        if run_log:
            run_log.write(
                "batch_skipped",
                batch=state.get("batch"),
                reason="All tokens already reported as failed",
                token_count=len(tokens),
            )
        print(f"Batch {state.get('batch')} skipped: all tokens already reported as failed.")
        return []

    brief = get_batch_brief(tokens)
    for item in brief or []:
        if isinstance(item, dict) and isinstance(item.get("token"), str):
            item["token"] = token_aliases.get(item["token"], item["token"][:6])
    if run_log:
        run_log.write("batch_brief", batch=state.get("batch"), files=brief)

    context_block = build_context_block(
        prior_context=prior_context,
        lookahead=lookahead,
        previous_tracks=previous_track_names,
        future_tracks=future_track_names,
        agent_thought=agent_thought,
        memory=memory,
        max_thought_tokens=max_thought_tokens,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Batch of "
                f"{len(tokens)} files. Here is the batch brief:\n"
                + json.dumps(brief, ensure_ascii=False, indent=2)
                + ("\n\n" + context_block if context_block else "")
                + "\nBegin. Finish every file, then call finish_batch."
            ),
        },
    ]
    staged, unresolved = [], []
    _last_assistant_content = ""
    _repeated_content_count = 0
    _recovery_used = False
    staged_stage_ids = {}
    verified_by_token = {}

    turn_cap = max(1, max_turns) * max(1, len(tokens))
    for turn in range(1, turn_cap + 1):
        if not debug_checkpoint(
            debug, f"Batch {state.get('batch')} model turn {turn}", run_log
        ):
            state.setdefault("errors", {}).update({
                token: "Debug run stopped before model turn."
                for token in tokens if token not in staged and token not in unresolved
            })
            state.update(summary="Stopped at debug checkpoint", staged=staged,
                         unresolved=unresolved, finished=False)
            save_state(state_path, state)
            return messages
        response = call_openrouter(messages, model, api_key, run_log=run_log)
        message = response["choices"][0]["message"]
        messages.append(message)
        _assistant_content = str(message.get("content") or "").strip()
        if _assistant_content and _assistant_content == _last_assistant_content:
            _repeated_content_count += 1
        elif _assistant_content:
            _last_assistant_content = _assistant_content
            _repeated_content_count = 0

        tool_calls = message.get("tool_calls") or []
        if (
            not tool_calls
            and _assistant_content
            and _repeated_content_count >= 1
        ):
            if not _recovery_used:
                _recovery_used = True
                messages = remove_last_prompt(messages)
                if staged:
                    write_successes_to_memory(staged=staged)
                messages.append({
                    "role": "user",
                    "content": (
                        "Repeated response detected. Remove the last prompt, "
                        "compact context, write successes to memory, and try "
                        "a different action. Limit initial context and use "
                        "list_tools to discover tool paths."
                    ),
                })
                continue
            for token in tokens:
                if token not in staged and token not in unresolved:
                    unresolved.append(token)
                    state.setdefault("errors", {})[token] = (
                        "Procrastination loop detected; skipped to next track."
                    )
            state.update(
                summary="Procrastination loop detected",
                staged=staged,
                unresolved=unresolved,
                finished=False,
            )
            save_state(state_path, state)
            if run_log:
                run_log.write(
                    "batch_procrastination_loop", batch=state.get("batch"),
                    staged=staged, unresolved=unresolved,
                )
            print("  procrastination loop detected; skipping remaining files", flush=True)
            return messages
        if not tool_calls:
            if (message.get("content") or "").strip():
                if run_log:
                    run_log.write(
                        "assistant_progress", batch=state.get("batch"), turn=turn,
                        visible_summary=message.get("content"),
                    )
                messages.append({
                    "role": "user",
                    "content": "Continue until every file is staged or marked "
                    "unresolved, then call finish_batch.",
                })
            continue

        abort_batch = False
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}

            if run_log:
                run_log.write(
                    "tool_call", batch=state.get("batch"), turn=turn,
                    tool=name, arguments=args,
                )

            token = args.get("token")
            if isinstance(token, str):
                token = short_to_full.get(token, token)
                if "token" in args:
                    args["token"] = token
            token_tools = {
                "read_track_metadata", "extract_filename_clues", "verify_mbid",
                "stage_tag_changes", "mark_unresolved", "identify_acrcloud",
            }
            if name in token_tools and token not in tokens:
                result = {"error": "Token is not part of the active batch."}
                messages.append({
                    "role": "tool", "tool_call_id": call["id"],
                    "content": json.dumps(result),
                })
                if run_log:
                    run_log.write("tool_result", batch=state.get("batch"),
                                  tool=name, result=result)
                continue

            if name in token_tools and token in (staged + unresolved):
                result = {"error": "This file was already resolved in this batch."}
                messages.append({
                    "role": "tool", "tool_call_id": call["id"],
                    "content": json.dumps(result),
                })
                if run_log:
                    run_log.write("tool_result", batch=state.get("batch"),
                                  tool=name, result=result)
                continue

            if name == "finish_batch":
                missing = [item for item in tokens if item not in staged and item not in unresolved]
                if missing:
                    result = {
                        "error": f"{len(missing)} file(s) are not resolved yet; process or mark them unresolved before finishing."
                    }
                    messages.append({
                        "role": "tool", "tool_call_id": call["id"],
                        "content": json.dumps(result),
                    })
                    if run_log:
                        run_log.write("finish_rejected", batch=state.get("batch"),
                                      unresolved_count=len(missing))
                    continue
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": "Batch complete. " + args.get("summary", ""),
                })
                state.update(
                    summary=args.get("summary", ""),
                    staged=staged,
                    unresolved=unresolved,
                    finished=True,
                )
                save_state(state_path, state)
                if run_log:
                    run_log.write("batch_finished", batch=state.get("batch"),
                                  summary=state.get("summary"), staged=staged,
                                  unresolved=unresolved)
                return messages

            if name == "mark_unresolved":
                reason = str(args.get("reason", "No safe match"))[:200]
                if token and token not in staged and token not in unresolved:
                    unresolved.append(token)
                    state.setdefault("errors", {})[token] = reason
                print(f"  unresolved: {token} — {reason}", flush=True)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": "Recorded as unresolved: " + reason,
                })
                if run_log:
                    run_log.write("track_unresolved", batch=state.get("batch"),
                                  token=token, reason=reason)
                continue

            if name == "stage_tag_changes":
                if not debug_checkpoint(
                    debug,
                    f"Stage proposal for {args.get('token')} ({args.get('new_tags', {})})",
                    run_log,
                ):
                    state.setdefault("errors", {}).update({
                        item: "Debug run stopped before staging this file."
                        for item in tokens if item not in staged and item not in unresolved
                    })
                    state.update(summary="Stopped at debug checkpoint", staged=staged,
                                 unresolved=unresolved, finished=False)
                    abort_batch = True
                    break
                verification = verified_by_token.get(token)
                requested_mbid = args.get("mb_recording_id")
                if (
                    not verification
                    or verification.get("verified") is not True
                    or float(verification.get("confidence", 0)) < 75.0
                    or (requested_mbid and requested_mbid != verification.get("recording_id"))
                ):
                    result = {"error": "Staging blocked: this file has no matching verified recording."}
                    messages.append({
                        "role": "tool", "tool_call_id": call["id"],
                        "content": json.dumps(result),
                    })
                    if run_log:
                        run_log.write("staging_blocked", batch=state.get("batch"),
                                      token=token, reason=result["error"])
                    continue
                args["mb_recording_id"] = verification["recording_id"]
                args["forensic_score"] = verification["confidence"]
                if not args.get("mb_release_id"):
                    args["mb_release_id"] = (verification.get("top_release") or {}).get("release_id")
                # Genre cleanup: prefer the agent's cleaned genre; fall back to a
                # cleaned MusicBrainz genre only when the agent omitted one.
                mb_genre = _clean_genre_value(verification.get("genre"))
                new_tags = dict(args.get("new_tags") or {})
                agent_genre = _clean_genre_value(new_tags.get("genre", ""))
                if agent_genre:
                    new_tags["genre"] = agent_genre
                elif mb_genre:
                    new_tags["genre"] = mb_genre
                if new_tags.get("genre"):
                    args["new_tags"] = new_tags

            fn = LOCAL_TOOLS.get(name)
            try:
                result = fn(**args) if fn else {"error": f"Unknown tool {name}"}
            except Exception as error:
                result = {"error": f"{type(error).__name__}: {str(error)[:300]}"}
            result = json.loads(json.dumps(result, ensure_ascii=False, default=str))

            if name == "stage_tag_changes":
                if "error" not in result:
                    staged.append(token)
                    state.setdefault("errors", {}).pop(token, None)
                    if isinstance(result, dict) and result.get("stage_id"):
                        staged_stage_ids[token] = result["stage_id"]
                    print(f"  staged: {token}", flush=True)
                else:
                    state.setdefault("errors", {})[token] = str(result["error"])
            elif name == "withdraw_staged_change":
                stage_id = args.get("stage_id")
                token_for_stage = None
                for tok, sid in staged_stage_ids.items():
                    if sid == stage_id:
                        token_for_stage = tok
                        break
                if "error" not in result and token_for_stage:
                    if token_for_stage in staged:
                        staged.remove(token_for_stage)
                    if token_for_stage in (state.get("staged") or []):
                        state["staged"] = [t for t in state["staged"] if t != token_for_stage]
                    staged_stage_ids.pop(token_for_stage, None)
                    print(f"  withdrew: {token_for_stage} ({stage_id})", flush=True)
            elif name == "verify_mbid" and isinstance(result, dict):
                if result.get("verified") is True and float(result.get("confidence", 0)) >= 75.0:
                    verified_by_token[token] = result
                else:
                    state.setdefault("errors", {})[token] = (
                        result.get("error") or "; ".join(result.get("mismatches", []))
                        or "Recording verification did not pass."
                    )

            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, ensure_ascii=False)[:6000],
            })
            if run_log:
                run_log.write("tool_result", batch=state.get("batch"), tool=name,
                              token=token, result=result)

        if abort_batch:
            save_state(state_path, state)
            return messages

        save_state(state_path, state)
        print(f"  turn {turn}: {len(staged)} staged, {len(unresolved)} unresolved")

    for token in tokens:
        if token not in staged and token not in unresolved:
            unresolved.append(token)
            state.setdefault("errors", {})[token] = (
                "Iteration cap reached before the file was resolved."
            )
    state.update(
        summary="Iteration cap reached",
        staged=staged,
        unresolved=unresolved,
        finished=False,
    )
    save_state(state_path, state)
    if run_log:
        run_log.write("batch_iteration_cap", batch=state.get("batch"),
                      staged=staged, unresolved=unresolved,
                      errors=state.get("errors", {}))
    return messages


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def select_job_id(requested_job_id, jobs, state=None, state_path=None):
    """Resolve an explicit id, a remembered job, or the first available job."""
    if requested_job_id:
        status = jobs.job_status(requested_job_id)
        if "error" in status:
            raise SystemExit(status["error"])
        return requested_job_id

    if state is None and state_path is not None:
        state = {}
        try:
            path = Path(state_path)
            if path.exists():
                state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            state = {}
    if isinstance(state, (str, Path)):
        try:
            path = Path(state)
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            state = {}

    try:
        available = jobs.list_jobs()
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    if not available:
        raise SystemExit("No available playlist jobs. Register a playlist first.")
    available_ids = [job["job_id"] for job in available]

    remembered = None
    if isinstance(state, dict):
        remembered = state.get("job_id") or state.get("last_job_id")
    if remembered in available_ids:
        print(f"Using last assigned playlist job: {remembered}")
        return remembered

    job_id = available[0]["job_id"]
    print(f"Using first available playlist job: {job_id}")
    return job_id


_RUN_LOG = None

_INTERRUPT_CONTEXT: dict = {
    "job_id": None,
    "jobs": None,
    "state": None,
    "state_path": None,
    "tokens": [],
    "batch_state": None,
}


def _handle_sigint(signum, frame):
    ctx = _INTERRUPT_CONTEXT
    jobs = ctx.get("jobs")
    job_id = ctx.get("job_id")
    tokens = list(ctx.get("tokens") or [])
    batch_state = ctx.get("batch_state")
    state = ctx.get("state")
    state_path = ctx.get("state_path")
    run_log = ctx.get("run_log") or globals().get("_RUN_LOG")
    if run_log:
        try:
            run_log.write(
                "run_interrupted",
                job_id=job_id,
                batch=(batch_state.get("batch") if isinstance(batch_state, dict) else None),
                token_count=len(tokens),
            )
        except Exception:
            pass
    print("\nInterrupted by user; returning claimed files to pending...", flush=True)
    if jobs is not None and job_id is not None and tokens:
        try:
            completed = set()
            if isinstance(batch_state, dict):
                completed = set(batch_state.get("staged") or []) | set(
                    batch_state.get("unresolved") or []
                )
            if completed:
                errors = (batch_state or {}).get("errors") or {}
                results = [
                    {
                        "token": token,
                        "success": token in (batch_state or {}).get("staged", []),
                        "error": errors.get(token, "Interrupted by user"),
                    }
                    for token in tokens
                    if token in completed
                ]
                if results:
                    jobs.complete_batch(job_id, results)
            unprocessed = [token for token in tokens if token not in completed]
            if unprocessed:
                released = jobs.release_batch(job_id, unprocessed)
                print(
                    f"Released {len(released.get('released', []))} file(s) to pending.",
                    flush=True,
                )
        except Exception as error:  # pragma: no cover - best effort
            print(f"Failed to release claimed files: {error}", flush=True)
    if state is not None and state_path is not None:
        try:
            state["memory"] = read_memory()
            metadata = memory_file_metadata()
            state["memory_path"] = metadata["path"]
            state["memory_mtime"] = metadata.get("mtime")
            state["memory_sha256"] = metadata.get("sha256")
            save_state(Path(state_path), state)
        except Exception:
            pass
    raise SystemExit(130)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "job_id",
        nargs="?",
        help="Playlist job id; omitted when there is exactly one available job",
    )
    parser.add_argument("--model", default="openrouter/free")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--lookahead", type=int, default=10,
                        help="Number of upcoming (unclaimed) files to show for album detection")
    parser.add_argument("--context-chars", type=int, default=4000,
                        help="Maximum characters of prior-batch context to retain")
    parser.add_argument("--compaction-model", default=None,
                        help="Model used by the separate post-run context compaction call")
    parser.add_argument("--no-compact-context", action="store_true",
                        help="Disable the separate OpenRouter context compaction call")
    parser.add_argument("--thought-tokens", type=int, default=10000,
                        help="Maximum tokens of prior agent thought to retain")
    parser.add_argument("--max-batches", type=int, default=None,
                        help="Stop after this many batches (useful for a trial run)")
    parser.add_argument("--max-consecutive-incomplete", type=int, default=3,
                        help="Skip stuck tracks after this many consecutive incomplete batches; 0 disables the limit")

    parser.add_argument("--max-turns", type=int, default=15,
                        help="Model turns allowed per file in a batch; batches loop until complete")
    parser.add_argument("--state", type=Path, default=Path("agent_state.json"))
    parser.add_argument(
        "--log", type=Path, default=None,
        help="JSONL run log path (defaults to the private data directory)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Pause at safe batch, model-request, and staging checkpoints",
    )
    parser.add_argument("--resume", action="store_true",
                        help="Skip files recorded as staged in the state file")
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = args.log or (ensure_data_subdirectory("agent_logs") /
                            f"openrouter-{timestamp}-{run_id[:8]}.jsonl")
    run_log = RunLog(log_path, run_id)
    global _RUN_LOG
    _RUN_LOG = run_log
    print(f"Run log: {log_path}")

    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
    RECENT_TRACKS.clear()
    RECENT_TRACKS.extend(state.get("seen_tracks", []))
    jobs = JobStore()
    job_id = select_job_id(args.job_id, jobs, state=state, state_path=args.state)
    state["job_id"] = job_id
    state["last_job_id"] = job_id

    _INTERRUPT_CONTEXT.update(
        job_id=job_id, jobs=jobs, state=state, state_path=args.state,
        tokens=[], batch_state=None, run_log=run_log,
    )
    signal.signal(signal.SIGINT, _handle_sigint)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("Set OPENROUTER_API_KEY (create one at https://openrouter.ai/keys)")

    status = jobs.job_status(job_id)
    if "error" in status:
        sys.exit(status["error"])
    print(f"Job {job_id} ({status['playlist_name']!r}): "
          f"{status['counts']['pending']} pending")
    run_log.write(
        "run_started", job_id=job_id, playlist_name=status["playlist_name"],
        model=args.model, batch_size=args.batch_size,
        max_batches=args.max_batches, max_turns=args.max_turns,
        debug=args.debug,
        starting_counts=status["counts"],
    )

    done = set(state.get("staged_by_file", [])) if args.resume else set()

    # Scan and review importance of scratchpad items before starting a batch.
    _memory_metadata = memory_file_metadata()
    if memory_is_stale(state, path=_memory_metadata["path"]):
        _scratchpad_raw = read_memory(path=_memory_metadata["path"])
        _scratchpad_reviewed = review_scratchpad(_scratchpad_raw)
        if _scratchpad_reviewed and _scratchpad_reviewed != _scratchpad_raw.strip():
            write_memory(_scratchpad_reviewed, path=_memory_metadata["path"])
            _memory_metadata = memory_file_metadata(path=_memory_metadata["path"])
    else:
        _scratchpad_raw = state.get("memory", "") or read_memory(path=_memory_metadata["path"])
        _scratchpad_reviewed = review_scratchpad(_scratchpad_raw)
    state["memory"] = _scratchpad_reviewed or _scratchpad_raw
    state["memory_path"] = _memory_metadata["path"]
    state["memory_mtime"] = _memory_metadata.get("mtime")
    state["memory_sha256"] = _memory_metadata.get("sha256")
    if run_log:
        run_log.write("scratchpad_reviewed", batch=0,
                      original_chars=len(_scratchpad_raw or ""),
                      reviewed_chars=len(_scratchpad_reviewed or ""))

    consecutive_incomplete = 0
    batch_number = 0
    while True:
        if not debug_checkpoint(
            args.debug, f"Claim the next batch of up to {args.batch_size} files?",
            run_log,
        ):
            print("Stopped before claiming another batch.")
            break
        claim = jobs.next_batch(job_id, size=args.batch_size)
        if "error" in claim:
            sys.exit(claim["error"])
        if not claim["batch"]:
            break
        batch_number += 1
        tokens = [entry["token"] for entry in claim["batch"]]
        names = [entry["display_name"] for entry in claim["batch"]]
        lookahead_names = jobs.peek_pending(job_id, size=max(0, args.lookahead))
        _INTERRUPT_CONTEXT["tokens"] = tokens
        state.setdefault("seen_tracks", [])
        for name in names:
            if name not in state["seen_tracks"]:
                state["seen_tracks"].append(name)
        RECENT_TRACKS.clear()
        RECENT_TRACKS.extend(state["seen_tracks"])

        # Skip a claimed batch when every display name was already reported as
        # failed in a previous run, so we do not re-send it to the model.
        skip_batch = bool(names) and all(
            name in set(state.get("failed_by_file", [])) for name in names
        )
        if skip_batch:
            print(f"Batch {batch_number} skipped: all tokens already reported as failed.")
            run_log.write(
                "batch_skipped",
                batch=batch_number,
                reason="All tokens already reported as failed",
                files=names,
            )

        batch_state = {
            "batch": batch_number,
            "files": names,
            "tokens": tokens,
            "staged": [],
            "unresolved": [],
            "finished": False,
        }
        _INTERRUPT_CONTEXT["batch_state"] = batch_state
        if skip_batch:
            batch_state["unresolved"] = list(tokens)
            batch_state["errors"] = {
                token: "Reported as failed in a previous run" for token in tokens
            }
            batch_state["finished"] = True
            batch_state["summary"] = "Skipped: all tokens already reported as failed"

        print(f"Batch {batch_number} ({claim['remaining']} after): {', '.join(names)}")
        run_log.write("batch_claimed", batch=batch_number, files=names,
                      token_count=len(tokens), pending_after_claim=claim["remaining"])

        if skip_batch:
            pass
        elif debug_checkpoint(
            args.debug,
            f"Submit batch {batch_number} metadata to OpenRouter model {args.model}?",
            run_log,
        ):
            batch_messages = []
            try:
                batch_messages = run_batch(
                    tokens, args.model, api_key, args.max_turns, batch_state,
                    args.state, run_log=run_log, debug=args.debug,
                    prior_context=state.get("context", ""),
                    lookahead=lookahead_names,
                    previous_tracks=list(dict.fromkeys(
                        (state.get("staged_by_file") or [])
                        + (state.get("failed_by_file") or [])
                    )),
                    future_tracks=lookahead_names,
                    agent_thought=state.get("agent_thought", ""),
                    memory=state.get("memory") if state.get("memory") is not None else read_memory(),
                    max_thought_tokens=args.thought_tokens,
                )
            except Exception as error:
                detail = _sanitize_log(f"{type(error).__name__}: {error}")
                run_log.write("batch_error", batch=batch_number, error=detail)
                batch_state["summary"] = "Agent run failed"
                batch_state["finished"] = False
                batch_state.setdefault("errors", {}).update({
                    token: str(detail)[:300]
                    for token in tokens
                    if token not in batch_state.get("staged", [])
                    and token not in batch_state.get("unresolved", [])
                })
        else:
            batch_state["summary"] = "Stopped before sending the batch to OpenRouter"
            batch_state["finished"] = False
            released = jobs.release_batch(job_id, tokens)
            run_log.write("batch_released", batch=batch_number,
                          reason="Debug stop before model submission", result=released)
            print(f"Released {len(released.get('released', []))} files to pending.")
            break

        new_thought = extract_agent_thought(batch_messages)
        if new_thought:
            state["agent_thought"] = _trim_to_tokens(
                _deduplicate_thought(
                    (state.get("agent_thought", "") + "\n" + new_thought).strip()
                ),
                args.thought_tokens,
            )

        errors = batch_state.get("errors", {})
        completed_tokens = set(batch_state["staged"]) | set(batch_state["unresolved"])
        results = [
            {
                "token": token,
                "success": token in batch_state["staged"],
                "error": errors.get(token, "Agent did not stage or resolve this file"),
            }
            for token in tokens if token in completed_tokens
        ]
        completion = jobs.complete_batch(job_id, results)
        unprocessed = [token for token in tokens if token not in completed_tokens]
        will_skip_stuck = (
            bool(unprocessed)
            and args.max_consecutive_incomplete
            and (consecutive_incomplete + 1) >= args.max_consecutive_incomplete
        )
        if will_skip_stuck:
            release_result = {"released": [], "unchanged": list(unprocessed)}
        else:
            release_result = jobs.release_batch(job_id, unprocessed) if unprocessed else {
                "released": [], "unchanged": [],
            }
        run_log.write("batch_completed", batch=batch_number,
                      outcomes=completion,
                      released=release_result,
                      staged_count=len(batch_state["staged"]),
                      unresolved_count=len(batch_state["unresolved"]),
                      finished=batch_state["finished"])

        staged_names = [
            names[i] for i, tok in enumerate(tokens) if tok in batch_state["staged"]
        ]
        unresolved_names = [
            names[i] for i, tok in enumerate(tokens) if tok in batch_state.get("unresolved", [])
        ]
        context_line = (
            f"Batch {batch_number}: staged={staged_names}; "
            f"unresolved={unresolved_names}; "
            f"summary={batch_state.get('summary', '')}"
        )
        state["context"] = (state.get("context", "") + "\n" + context_line).strip()
        # Compact the context: remove failed output and trim to budget.
        _failed_for_context = set(state.get("failed_by_file", []) or [])
        if getattr(args, "no_compact_context", False):
            state["context"] = compact_context(
                state["context"], failed=_failed_for_context,
                max_chars=args.context_chars,
            )
        else:
            _compaction_model = getattr(args, "compaction_model", None) or args.model
            if api_key:
                state["context"] = compact_context_with_openrouter(
                    state["context"], model=_compaction_model, api_key=api_key,
                    failed=_failed_for_context, max_chars=args.context_chars,
                    run_log=run_log,
                )
            else:
                state["context"] = compact_context(
                    state["context"], failed=_failed_for_context,
                    max_chars=args.context_chars,
                )
        state.setdefault("staged_by_file", []).extend(sorted(set(staged_names) - done))
        state.setdefault("failed_by_file", []).extend(
            sorted(set(unresolved_names) - set(state.get("failed_by_file", [])))
        )
        state["memory"] = read_memory()
        _memory_metadata = memory_file_metadata()
        state["memory_path"] = _memory_metadata["path"]
        state["memory_mtime"] = _memory_metadata.get("mtime")
        state["memory_sha256"] = _memory_metadata.get("sha256")
        save_state(args.state, state)

        print(
            f"Batch {batch_number} result: {len(batch_state['staged'])} staged, "
            f"{len(batch_state['unresolved'])} unresolved, "
            f"{len(unprocessed)} returned to pending."
        )

        if unprocessed:
            consecutive_incomplete += 1
            print(
                f"Incomplete batch: {len(unprocessed)} returned to pending "
                f"(consecutive incomplete: {consecutive_incomplete})."
            )
            if (
                args.max_consecutive_incomplete
                and consecutive_incomplete >= args.max_consecutive_incomplete
            ):
                skip_results = [
                    {
                        "token": token,
                        "success": False,
                        "error": "Skipped after repeated incomplete batches.",
                    }
                    for token in unprocessed
                ]
                jobs.complete_batch(job_id, skip_results)
                print(
                    f"Skipped {len(unprocessed)} stuck track(s) after "
                    f"{consecutive_incomplete} consecutive incomplete batches; "
                    "continuing with remaining work."
                )
                consecutive_incomplete = 0
                continue
            print(f"Released {len(release_result.get('released', []))} files to pending.")
            continue

        consecutive_incomplete = 0

        if args.max_batches is not None and batch_number >= args.max_batches:
            print(f"Stopped after requested limit of {args.max_batches} batch(es).")
            break

    status = jobs.job_status(job_id)
    counts = status["counts"]
    print(
        f"Done. {counts['done']} done, {counts['failed']} failed, "
        f"{counts['in_progress']} in progress. "
        "Review staged manifests, then run apply_staged to write tags."
    )
    run_log.write("run_finished", job_id=job_id, final_counts=counts,
                  batches_processed=batch_number)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except Exception as error:
        print(f"Fatal error: {type(error).__name__}: {error}", flush=True)
        run_log = globals().get("_RUN_LOG")
        if run_log is not None:
            try:
                run_log.write("run_failed", error=str(error)[:500])
            except Exception:
                pass
        raise SystemExit(1)

# Public aliases for anti-loop helpers.
remove_last_user_message = remove_last_prompt
remove_last_prompt_from_context = remove_last_prompt
limit_context = limit_initial_context
trim_initial_context = limit_initial_context
write_successes = write_successes_to_memory
record_successes = write_successes_to_memory
save_successes = write_successes_to_memory
expose_tools = expose_tool_paths
list_tools_paths = expose_tool_paths
def _resolve_compaction_source(context=None, prior_context=None, text=None,
                              messages=None, **kwargs):
    """Resolve the text to compact from a variety of accepted inputs."""
    source = None
    if text is not None:
        source = text
    elif prior_context is not None:
        source = prior_context
    elif context is not None and not isinstance(context, (list, tuple, dict)):
        source = context
    elif isinstance(context, (list, tuple)):
        messages = list(context)
    if source is None and messages is not None:
        lines = []
        for item in messages:
            if isinstance(item, dict):
                role = item.get("role", "")
                content = item.get("content", "")
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            parts.append(str(part.get("text", part)))
                        else:
                            parts.append(str(part))
                    content = " ".join(parts)
                lines.append(f"{role}: {content}".strip())
            else:
                lines.append(str(item))
        source = "\n".join(lines)
    if source is None:
        for key in ("context", "prior_context", "old_context", "value"):
            if kwargs.get(key) is not None and not isinstance(kwargs.get(key), (list, tuple, dict)):
                source = kwargs.get(key)
                break
    if source is None:
        source = ""
    return str(source).strip()


def _extract_openrouter_content(response):
    """Extract assistant text from an OpenRouter/OpenAI response."""
    try:
        choices = response.get("choices", []) if isinstance(response, dict) else getattr(response, "choices", [])
        if not choices:
            return ""
        first = choices[0]
        message = first.get("message", {}) if isinstance(first, dict) else getattr(first, "message", None)
        if isinstance(message, dict):
            content = message.get("content", "")
        else:
            content = getattr(message, "content", "") if message is not None else ""
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text", "")))
                else:
                    parts.append(str(part))
            content = " ".join(parts)
        return str(content or "").strip()
    except Exception:
        return ""


def _strip_markdown_fences(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


COMPACTION_SYSTEM_PROMPT = (
    "You are a context compaction assistant for a music metadata tagging agent. "
    "Your only job is to compact the provided agent context. Return only the "
    "compacted context text, with no commentary and no markdown fences. Remove "
    "all failed tracks, failed attempts, mentions of failures, errors, repeated "
    "messages, and duplicate lines. Preserve successful staged tracks, verified "
    "matches, album/release consistency clues, and concise notes needed for "
    "future batches."
)
def compact_context_with_openrouter(context="", *, model=None, api_key=None,
                                   prior_context=None, text=None, messages=None,
                                   max_chars=None, max_context_chars=None,
                                   context_chars=None, run_log=None,
                                   temperature=0.2, fallback=True, **kwargs):
    """Compact context using a separate OpenRouter call.

    The separate call is instructed to remove failures, mentions of failures, and
    duplicated messages. Falls back to deterministic compaction if the call fails
    or returns no usable text.
    """
    source = _resolve_compaction_source(
        context=context, prior_context=prior_context, text=text,
        messages=messages, **kwargs)
    if not source:
        return ""

    if model is None:
        model = kwargs.get("model") or kwargs.get("compaction_model")
    if model is None:
        model = os.environ.get("OPENROUTER_COMPACTION_MODEL") or os.environ.get("OPENROUTER_MODEL")
    if not model:
        model = "openrouter/free"
    if api_key is None:
        api_key = kwargs.get("api_key") or kwargs.get("openrouter_api_key")
    if api_key is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
    if api_key is None:
        api_key = ""

    budget = max_chars if max_chars is not None else max_context_chars
    if budget is None:
        budget = context_chars
    if budget is None:
        budget = kwargs.get("max_chars") or kwargs.get("context_chars")
    try:
        budget = int(budget) if budget is not None else None
    except (TypeError, ValueError):
        budget = None

    failed_set = set()
    for key in ("failed", "failed_names", "failed_files", "unresolved", "failed_by_file"):
        value = kwargs.get(key)
        if value:
            if isinstance(value, (list, tuple, set)):
                failed_set.update(value)
            else:
                failed_set.add(value)

    compacted = ""
    try:
        request_messages = [
            {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
            {"role": "user", "content": (
                "Compact the following agent context. Remove failures, mentions "
                "of failures, and duplicated messages. Keep it concise and useful "
                "for future batches. Return only the compacted context.\n\n"
                f"<context>\n{source}\n</context>"
            )},
        ]
        response = call_openrouter(
            request_messages, model, api_key, temperature=temperature,
            retries=1, run_log=run_log, stream=False, tools=[])
        compacted = _strip_markdown_fences(_extract_openrouter_content(response))
    except Exception:
        compacted = ""

    if not compacted and fallback:
        compacted = compact_context(
            source, failed=failed_set, max_chars=budget, max_context_chars=budget,
            context_chars=budget)

    if compacted:
        compacted = compact_context(
            compacted, failed=failed_set, max_chars=budget,
            max_context_chars=budget, context_chars=budget)
    return compacted.strip()
"""
compact_context_via_openrouter = compact_context_with_openrouter
openrouter_compact_context = compact_context_with_openrouter
llm_compact_context = compact_context_with_openrouter
compact_with_openrouter = compact_context_with_openrouter
compact_context_llm = compact_context_with_openrouter
compact_context_using_model = compact_context_with_openrouter
compact_context_with_model = compact_context_with_openrouter
compact_context_openrouter = compact_context_with_openrouter
compact_after_run = compact_context_with_openrouter
compact_run_context = compact_context_with_openrouter
compact_context_after_run = compact_context_with_openrouter
run_context_compaction = compact_context_with_openrouter
context_compact_openrouter = compact_context_with_openrouter
"""
