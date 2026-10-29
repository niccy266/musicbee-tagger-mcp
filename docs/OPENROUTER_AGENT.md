# OpenRouter Agent Loop

A model-driven batch agent that wraps the MusicBee Tagger MCP tools. It
processes audio files in batches of 10, using OpenRouter's OpenAI-compatible
chat completions endpoint with function calling.

## How it works

1. A playlist job is created by the human-run registration CLI — only opaque
   tokens, a job id, and bare filenames ever reach the model (same privacy
   model as the MCP server). The MCP `list_jobs` tool shows
   path-free summaries for jobs with pending tracks. If exactly one job is
   available, the loop selects it automatically; otherwise pass a job id.
2. The agent claims batches of up to 10 unprocessed tokens via `next_batch`.
3. The loop sends a batch brief (existing tags, durations, filename clues) to
   the model with a system prompt adapted from the `musicbee-investigator`
   skill.
4. The model decides which tools to call. The loop executes them locally:
   - inspection: `read_track_metadata`, `extract_filename_clues`,
     `get_batch_brief`
   - identity: `search_canonical_release`, `verify_mbid` (the mandatory gate),
     `identify_acrcloud`, `web_search`
   - text: `repair_mojibake`
   - artist splits: `propose_artist_split`, `search_musicbrainz_artist`,
     `verify_artists_on_recording`, `flag_suspicious_artists`
   - staging: `preview_tags`, `stage_tag_changes` (manifest only — no audio
     writes)
   - batch/queue: `next_batch`, `complete_batch`, `release_batch`,
     `job_status`, `list_jobs`, `enqueue_batch_operation`,
     `list_batch_operations`, `update_batch_operation`
5. A verified recording is required by the local harness before it permits
   `stage_tag_changes`. Failed verification can be retried or explicitly marked
   unresolved.
6. Each `finish_batch` is checked against all batch tokens. Outcomes are
   recorded with `complete_batch`; model/API errors are logged and claimed work
   is completed as failed rather than left in progress.
7. A JSON state file records progress. A path-sanitized JSONL log records batch
   briefs, visible model summaries, tool calls/results, timing, and errors.
   OpenRouter does not expose hidden chain-of-thought; logs contain only
   user-visible summaries and tool activity.

## Usage

```sh
pip install musicbee-tagger-mcp  # or run from a source checkout
export OPENROUTER_API_KEY=sk-or-...
python scripts/openrouter_agent_loop.py [job_id] \
    --model openrouter/free --batch-size 10 --max-batches 3 --max-turns 15 \
    --debug --resume
```

Context compaction is on by default and trims failures, failure mentions and
repeated messages from the history mid-run; `--compaction-model` runs that
summarisation through a separate (typically cheaper) OpenRouter model, and
`--no-compact-context` disables compaction entirely. `--context-chars` bounds
how much of each tool result stays in context and `--thought-tokens` bounds the
visible summary budget.

Logs default to the private application data directory's `agent_logs` folder.
`--max-consecutive-incomplete` (default 3; use 0 to disable) controls how many incomplete batches may occur before stuck tracks are skipped; otherwise released tracks are retried on later iterations.
`--debug` pauses before claiming a batch, submitting metadata to OpenRouter,
each model turn, and each stage operation; press Enter to continue or `q` to
stop at that checkpoint. Without `--debug`, no pause prompts occur.

Omit `job_id` when exactly one job has pending tracks. If multiple jobs are
available, the script lists their IDs and asks you to specify one. Use the MCP
`list_jobs` tool to inspect available jobs without exposing paths or track
tokens.

## Model choice

Any OpenRouter model works (`openrouter/free` is the default). The
system prompt is model-agnostic; tool calls follow the standard OpenAI
function-calling format. Alias slugs like `~openai/gpt-sol-latest` always
resolve to the newest model in a family.

## Safety
- Do not run shell commands (bash, cmd, powershell, python, etc.) without first making absolutely sure that the required action cannot be performed using an existing exposed tool (MCP tool, skill, or other available tool). Prefer the exposed tool; use a shell only as a last resort and state why no exposed tool can do it.


- Staging never writes audio files. Apply still requires the separate
  `apply_staged` CLI with interactive confirmation and backups.
- The batch brief sends filenames and existing tag metadata to the selected
  OpenRouter model. The local JSONL run log stays in the configured data
  directory unless `--log` supplies another path.
- Unknown tokens, invalid arguments, and unknown tool names return errors to
  the model rather than raising.
- Tool results are truncated to 6 KB per message to bound context growth.

## Costs

A batch of 10 files typically needs 15-40 tool-call turns; with a small model
this is well under USD 0.05 per batch. Check current pricing at
https://openrouter.ai/models.
