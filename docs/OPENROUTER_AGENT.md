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
   - `read_track_metadata`, `extract_filename_clues`, `repair_mojibake`
   - `search_canonical_release`, `verify_mbid` (the mandatory gate)
   - `stage_tag_changes` (manifest only — no audio writes)
5. `verify_mbid` failures below the 0.75 threshold are recorded as unresolved.
6. Each call to `finish_batch` or the `--max-turns` cap ends a batch. Outcomes
   are recorded with `complete_batch`; `job_status` reports counts only.
   A JSON state file records progress for resuming an interrupted run.

## Usage

```sh
pip install musicbee-tagger-mcp  # or run from a source checkout
export OPENROUTER_API_KEY=sk-or-...
python scripts/openrouter_agent_loop.py [job_id] \
    --model openai/gpt-4o-mini --max-turns 15 --resume
```

Omit `job_id` when exactly one job has pending tracks. If multiple jobs are
available, the script lists their IDs and asks you to specify one. Use the MCP
`list_jobs` tool to inspect available jobs without exposing paths or track
tokens.

## Model choice

Any OpenRouter model works (`openai/gpt-4o-mini` is a cheap default). The
system prompt is model-agnostic; tool calls follow the standard OpenAI
function-calling format. Alias slugs like `~openai/gpt-sol-latest` always
resolve to the newest model in a family.

## Safety

- Staging never writes audio files. Apply still requires the separate
  `apply_staged` CLI with interactive confirmation and backups.
- Unknown tokens, invalid arguments, and unknown tool names return errors to
  the model rather than raising.
- Tool results are truncated to 6 KB per message to bound context growth.

## Costs

A batch of 10 files typically needs 15-40 tool-call turns; with a small model
this is well under USD 0.05 per batch. Check current pricing at
https://openrouter.ai/models.
