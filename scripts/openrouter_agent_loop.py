#!/usr/bin/env python3
"""OpenRouter agent loop for the MusicBee Tagger MCP tools.

Runs a model-driven loop over batches of 10 registered files. The model
receives a batch brief, decides which tools to call (search, verify, stage),
and the loop executes those calls locally and feeds results back until the
batch is done or the iteration cap is hit.

Requires: OPENROUTER_API_KEY environment variable.
Usage:
    export OPENROUTER_API_KEY=sk-or-...
    python scripts/openrouter_agent_loop.py /path/to/music --model openai/gpt-4o-mini --apply

Notes:
    - Files are registered locally; only opaque tokens reach the model.
    - Staging is safe (manifest only). Tag writes still go through
      apply_staged.py after human review, unless --apply is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Allow running from a source checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from musicbee_tagger_mcp.file_registry import get_registry  # noqa: E402
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

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
RETRYABLE_STATUS = {429, 500, 502, 503}
AUDIO_SUFFIXES = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus", ".wma"}
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

Rules:
- Use tokens exactly as given; never invent tokens.
- One file at a time; do not revisit a file you already staged or marked
  unresolved.
- When every file in the batch is staged or explicitly marked unresolved in
  your final message, call finish_batch with a one-line summary.
- Be concise in tool arguments; do not repeat file contents back.
"""

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

LOCAL_TOOLS = {
    "read_track_metadata": lambda token: read_track_metadata(token),
    "extract_filename_clues": lambda token: extract_filename_clues(token),
    "repair_mojibake": lambda text: repair_mojibake(text),
    "search_canonical_release": search_canonical_release,
    "verify_mbid": verify_mbid,
    "stage_tag_changes": stage_tag_changes,
}


def call_openrouter(messages, model, api_key, temperature=0.2, retries=3):
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
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                temperature=temperature,
            )
            return response.model_dump(mode="json")
        except (APITimeoutError, APIStatusError) as error:
            status = getattr(error, "status_code", None)
            retryable = status in RETRYABLE_STATUS or status is None
            if retryable and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            detail = str(error)[:300]
            raise RuntimeError(f"OpenRouter error {status or 'timeout'}: {detail}")
    raise RuntimeError("OpenRouter unreachable")


def collect_audio_files(root: Path):
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES
    )


def run_batch(tokens, model, api_key, max_turns, state, state_path):
    """One agent loop over one batch of tokens. Returns the message history."""
    brief = get_batch_brief(tokens)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Batch of "
                f"{len(tokens)} files. Here is the batch brief:\n"
                + json.dumps(brief, ensure_ascii=False, indent=2)
                + "\nBegin. Finish every file, then call finish_batch."
            ),
        },
    ]
    staged, unresolved = [], []

    for turn in range(1, max_turns + 1):
        response = call_openrouter(messages, model, api_key)
        message = response["choices"][0]["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            if (message.get("content") or "").strip():
                messages.append({
                    "role": "user",
                    "content": "Continue until every file is staged or marked "
                    "unresolved, then call finish_batch.",
                })
            continue

        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "finish_batch":
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
                return messages

            fn = LOCAL_TOOLS.get(name)
            result = fn(**args) if fn else {"error": f"Unknown tool {name}"}
            result = json.loads(json.dumps(result, ensure_ascii=False, default=str))

            if name == "stage_tag_changes" and "error" not in result:
                staged.append(args.get("token"))
            elif name == "verify_mbid" and isinstance(result, dict):
                score = result.get("score") or result.get("confidence") or 0
                if score < 0.75:
                    unresolved.append(args.get("token"))

            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, ensure_ascii=False)[:6000],
            })

        save_state(state_path, state)
        print(f"  turn {turn}: {len(staged)} staged, {len(unresolved)} unresolved")

    state.update(
        summary="Iteration cap reached",
        staged=staged,
        unresolved=unresolved,
        finished=False,
    )
    save_state(state_path, state)
    return messages


def save_state(path, state):
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Folder of audio files")
    parser.add_argument("--model", default="openai/gpt-4o-mini")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("--state", type=Path, default=Path("agent_state.json"))
    parser.add_argument("--resume", action="store_true",
                        help="Skip files recorded as staged in the state file")
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("Set OPENROUTER_API_KEY (create one at https://openrouter.ai/keys)")

    files = collect_audio_files(args.folder)
    if not files:
        sys.exit(f"No audio files found under {args.folder}")

    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    done = set(state.get("staged_by_file", [])) if args.resume else set()

    print(f"{len(files)} audio files found")
    for start in range(0, len(files), args.batch_size):
        batch_paths = [p for p in files[start:start + args.batch_size] if p not in done]
        if not batch_paths:
            continue
        registry = get_registry()
        registered = registry.register_many([str(p) for p in batch_paths])
        tokens = [r["token"] for r in registered]
        names = [r["display_name"] for r in registered]

        batch_state = {
            "batch": start // args.batch_size + 1,
            "files": names,
            "tokens": tokens,
            "staged": [],
            "unresolved": [],
            "finished": False,
        }
        print(f"Batch {batch_state['batch']}: {', '.join(names)}")
        run_batch(tokens, args.model, api_key, args.max_turns, batch_state, args.state)

        staged_names = {
            names[i] for i, tok in enumerate(tokens) if tok in batch_state["staged"]
        }
        state.setdefault("staged_by_file", []).extend(sorted(staged_names))
        save_state(args.state, state)

    print(f"Done. Review staged manifests, then run apply_staged to write tags.")


if __name__ == "__main__":
    main()
