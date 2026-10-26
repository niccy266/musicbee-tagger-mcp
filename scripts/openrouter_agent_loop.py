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
import json
import os
import re
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
    search_canonical_release,
    verify_mbid,
)
from musicbee_tagger_mcp.tools.tags import (  # noqa: E402
    preview_tags,
    stage_tag_changes,
)
from musicbee_tagger_mcp.tools.text import repair_mojibake  # noqa: E402
from musicbee_tagger_mcp.job_store import JobStore  # noqa: E402
from musicbee_tagger_mcp.data_paths import ensure_data_subdirectory  # noqa: E402

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
RETRYABLE_STATUS = {429, 500, 502, 503}
BATCH_SIZE = 10

SYSTEM_PROMPT = """\
You are a music metadata agent. You are given a batch of audio files whose
identity is hidden behind opaque tokens. For each file:

1. Inspect it: call read_track_metadata and extract_filename_clues on its token.
2. Repair mojibake and search MusicBrainz: use repair_mojibake on any garbled
   text, then search_canonical_release with artist + title + duration.
3. Verify: call verify_mbid on the best candidate. If it fails (score < 0.75
   or duration/artist/title mismatch), retry with different search terms or
   mark the file unresolved — never stage an unverified match.
4. Stage: when verified, call stage_tag_changes with the corrected tags,
   mb_recording_id, mb_release_id, forensic_score, and a short note.

Genre cleanup is part of every verified match. Use the verified MusicBrainz
genre value when it is present: deduplicate exact repeated values and remove
obvious encoding damage only. Preserve meaningful existing genres and do not
replace them with an empty or weak result. Do not remove mood descriptors or
other non-genre values unless you can identify them as clear junk. Do not invent
genres. Include a corrected genre in new_tags when it is reliably supported.

Filename-derived artist/title values are search clues only. Do not stage them
without independent corroboration from existing tags, release credits, or a
verified recording match.

Context and look-ahead:
- You may receive prior context from earlier batches and a list of upcoming
  files not in this batch. Use them to recognize albums, series, and consistent
  release metadata, but only stage values after verifying each file.
- When several files in the current batch appear to belong to the same release,
  keep artist/album/release metadata consistent across them.

Rules:
- Use tokens exactly as given; never invent tokens.
- One file at a time; do not revisit a file you already staged or marked
  unresolved.
- When every file in the batch is staged or explicitly marked unresolved in
  your final message, call finish_batch with a one-line summary.
- Be concise in tool arguments; do not repeat file contents back.
- When useful, include a short visible progress summary in the assistant
  response. Do not provide private chain-of-thought.
"""

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
                "properties": {"token": {"type": "string"}},
                "required": ["token"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_filename_clues",
            "description": "Parse artist/title clues out of the file's name.",
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
            "name": "repair_mojibake",
            "description": "Detect and repair mojibake/encoding damage in text.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_canonical_release",
            "description": "Search MusicBrainz for the canonical release. "
            "Returns candidates with MBIDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "title": {"type": "string"},
                    "duration_seconds": {"type": "integer"},
                },
                "required": ["artist", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_mbid",
            "description": "Verify a MusicBrainz candidate against the file "
            "(duration/artist/title). Only verified matches may be staged.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                    "mb_recording_id": {"type": "string"},
                },
                "required": ["token", "mb_recording_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stage_tag_changes",
            "description": "Stage corrected tags for a file (manifest only, "
            "no audio write until apply).",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                    "new_tags": {
                        "type": "object",
                        "description": "Tag name -> value, e.g. "
                        "{\"title\": \"...\", \"artist\": \"...\", \"album\": \"...\"}",
                    },
                    "mb_recording_id": {"type": "string"},
                    "mb_release_id": {"type": "string"},
                    "forensic_score": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["token", "new_tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_unresolved",
            "description": "Record a file as unresolved with a short reason.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["token", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_batch",
            "description": "Call when every file in the batch is resolved.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
]

def _search_canonical_release(artist, title, duration_seconds=None):
    return search_canonical_release(
        artist=artist, title=title, duration_sec=duration_seconds
    )


def _verify_mbid(token, mb_recording_id):
    metadata = read_track_metadata(token)
    if "error" in metadata:
        return metadata
    tags = metadata.get("tags", {})
    return verify_mbid(
        recording_id=mb_recording_id,
        expected_artist=tags.get("artist"),
        expected_title=tags.get("title"),
        duration_sec=metadata.get("duration_seconds"),
    )


LOCAL_TOOLS = {
    "read_track_metadata": lambda token: read_track_metadata(token),
    "extract_filename_clues": lambda token: extract_filename_clues(token),
    "repair_mojibake": lambda text: repair_mojibake(text),
    "search_canonical_release": _search_canonical_release,
    "verify_mbid": _verify_mbid,
    "stage_tag_changes": stage_tag_changes,
}


def call_openrouter(messages, model, api_key, temperature=0.2, retries=3,
                   run_log=None, stream=True):
    """One chat completion with tool support, via the openai SDK pointed at
    OpenRouter (https://openrouter.ai/docs/quickstart#using-the-client-sdks).
    Returns the raw OpenAI-shaped dict the batch loop expects."""
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
                    tools=TOOLS,
                    temperature=temperature,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                content_parts = []
                tool_call_parts = {}
                finish_reason = None
                usage = None
                printed_prefix = False
                for chunk in response_stream:
                    if getattr(chunk, "usage", None) is not None:
                        try:
                            usage = chunk.usage.model_dump(mode="json")
                        except Exception:
                            usage = str(chunk.usage)
                    for choice in (chunk.choices or []):
                        finish_reason = choice.finish_reason or finish_reason
                        delta = choice.delta
                        if getattr(delta, "content", None):
                            if not printed_prefix:
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
                if printed_prefix:
                    print(flush=True)
                tool_calls = [tool_call_parts[idx] for idx in sorted(tool_call_parts)]
                message = {
                    "role": "assistant",
                    "content": "".join(content_parts) or None,
                }
                if tool_calls:
                    message["tool_calls"] = tool_calls
                    print(
                        "  -> tools: "
                        + ", ".join(tc["function"]["name"] for tc in tool_calls),
                        flush=True,
                    )
                payload = {
                    "choices": [{"message": message, "finish_reason": finish_reason}],
                    "usage": usage,
                }
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOLS,
                    temperature=temperature,
                )
                payload = response.model_dump(mode="json")
                choice = (payload.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                visible = (message.get("content") or "").strip()
                if visible:
                    print(f"[assistant] {visible}", flush=True)
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    print(
                        "  -> tools: "
                        + ", ".join(
                            tc.get("function", {}).get("name", "?")
                            for tc in tool_calls
                        ),
                        flush=True,
                    )

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
    raise RuntimeError("OpenRouter unreachable")


def run_batch(tokens, model, api_key, max_turns, state, state_path,
              run_log=None, debug=False, prior_context="", lookahead=None):
    """One agent loop over one batch of tokens. Returns the message history."""
    # Skip batches whose tokens were already reported as failed in an earlier run.
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
    if run_log:
        run_log.write("batch_brief", batch=state.get("batch"), files=brief)

    context_sections = []
    if prior_context and prior_context.strip():
        context_sections.append(
            "Prior context from earlier batches (compressed plaintext):\n"
            + prior_context.strip()
        )
    if lookahead:
        context_sections.append(
            "Upcoming files not in this batch (look-ahead; use for album/series detection):\n"
            + "\n".join(f"- {name}" for name in lookahead)
        )
    context_block = "\n\n".join(context_sections)

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

        tool_calls = message.get("tool_calls") or []
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
            token_tools = {
                "read_track_metadata", "extract_filename_clues", "verify_mbid",
                "stage_tag_changes", "mark_unresolved",
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
                # Auto-include genre from verified MusicBrainz recording if present
                mb_genre = verification.get("genre")
                if mb_genre and mb_genre.strip():
                    new_tags = dict(args.get("new_tags") or {})
                    current_genre = new_tags.get("genre", "").strip()
                    # Only add genre if it differs from current and is not empty/weak
                    if mb_genre != current_genre:
                        new_tags["genre"] = mb_genre
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
                else:
                    state.setdefault("errors", {})[token] = str(result["error"])
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

    state.update(
        summary="Iteration cap reached",
        staged=staged,
        unresolved=unresolved,
        finished=False,
    )
    state.setdefault("errors", {}).update({
        token: "Iteration cap reached before the file was resolved."
        for token in tokens if token not in staged and token not in unresolved
    })
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
    parser.add_argument("--max-batches", type=int, default=None,
                        help="Stop after this many batches (useful for a trial run)")
    parser.add_argument("--max-consecutive-incomplete", type=int, default=3,
                        help="Stop after this many consecutive incomplete batches; 0 disables the limit")

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
    print(f"Run log: {log_path}")

    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
    jobs = JobStore()
    job_id = select_job_id(args.job_id, jobs, state=state, state_path=args.state)
    state["job_id"] = job_id
    state["last_job_id"] = job_id

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
            try:
                run_batch(
                    tokens, args.model, api_key, args.max_turns, batch_state,
                    args.state, run_log=run_log, debug=args.debug,
                    prior_context=state.get("context", ""),
                    lookahead=lookahead_names,
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
        if len(state["context"]) > args.context_chars:
            state["context"] = state["context"][-args.context_chars:]
        state.setdefault("staged_by_file", []).extend(sorted(set(staged_names) - done))
        state.setdefault("failed_by_file", []).extend(
            sorted(set(unresolved_names) - set(state.get("failed_by_file", [])))
        )
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
                print(
                    "Stopping after repeated incomplete batches; "
                    "released tracks can be retried later."
                )
                break
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
    main()
