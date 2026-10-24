# OpenRouter Agent Loop

A model-driven batch agent that wraps the MusicBee Tagger MCP tools. It
processes audio files in batches of 10, using OpenRouter's OpenAI-compatible
chat completions endpoint with function calling.

## How it works

1. Files are collected from a folder and **registered locally** — only opaque
   tokens and bare filenames ever reach the model (same privacy model as the
   MCP server).
2. The loop sends a batch brief (existing tags, durations, filename clues) to
   the model with a system prompt adapted from the `musicbee-investigator`
   skill.
3. The model decides which tools to call. The loop executes them locally:
   - `read_track_metadata`, `extract_filename_clues`, `repair_mojibake`
   - `search_canonical_release`, `verify_mbid` (the mandatory gate)
   - `stage_tag_changes` (manifest only — no audio writes)
4. `verify_mbid` failures below the 0.75 threshold are recorded as unresolved.
5. Each call to `finish_batch` or the `--max-turns` cap ends a batch. Progress
   persists in a JSON state file, so an interrupted run resumes with `--resume`.

## Usage

```sh
pip install musicbee-tagger-mcp  # or run from a source checkout
export OPENROUTER_API_KEY=sk-or-...
python scripts/openrouter_agent_loop.py /path/to/music \
    --model openai/gpt-4o-mini --max-turns 15 --resume
```

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
