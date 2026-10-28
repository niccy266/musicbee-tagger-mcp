#!/usr/bin/env python3
"""Loop-based virtual terminal log monitor for the MusicBee Tagger agent.

This script provides a periodic checkup loop for the agent. It runs inside a
virtual terminal host and, on each tick:

    while true; do
        <run-agent-or-poll-command>
        sleep 5
        <print last log line>
    done

The loop is designed to give an operator periodic visibility into the agent's
state without requiring a persistent interactive session.

Usage:
    python scripts/_agent_monitor_loop.py            # default tick
    python scripts/_agent_monitor_loop.py --tick 30  # run every 30s
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow running from a source checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Expose agent helpers used by the monitor.
from musicbee_tagger_mcp.data_paths import ensure_data_subdirectory  # noqa: E402
from scripts import openrouter_agent_loop as agent  # noqa: E402


def default_log_path() -> Path:
    """Return the default JSONL run log path (agent_logs)."""
    return (
        ensure_data_subdirectory("agent_logs")
        / "openrouter-monitor-{}-{}.jsonl".format(
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            str(time.time()).replace(".", ""),
        )
    )


def last_log_line(log_path: Path, tail_lines: int = 5) -> list[str]:
    """Return the last `tail_lines` of a JSONL log file (or [] if absent)."""
    if not log_path.is_file():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return lines[-tail_lines:]


def summarize_log_event(record: dict) -> str:
    """Return a short human-readable summary of a single JSONL record."""
    event = record.get("event")
    if event == "run_started":
        return "run_started job={} model={}".format(
            record.get("job_id"), record.get("model")
        )
    if event == "batch_claimed":
        return "batch_claimed batch={} files={}".format(
            record.get("batch"), len(record.get("files", []))
        )
    if event == "batch_completed":
        return "batch_completed batch={} staged={} unresolved={}".format(
            record.get("batch"),
            record.get("staged_count"),
            record.get("unresolved_count"),
        )
    if event == "run_finished":
        counts = record.get("final_counts", {})
        return "run_finished counts=done={} failed={} in_progress={}".format(
            counts.get("done"), counts.get("failed"), counts.get("in_progress")
        )
    if event == "quit":
        return "quit label={}".format(record.get("label"))
    if event == "model_request_error":
        return "model_request_error attempt={} status={}".format(
            record.get("attempt"), record.get("status")
        )
    if event == "model_rate_limited":
        return "model_rate_limited wait={}s".format(record.get("wait_seconds"))
    if event == "debug_checkpoint":
        return "debug_checkpoint label={} choice={}".format(
            record.get("label"), record.get("choice")
        )
    summary = record.get("summary") or record.get("error") or ""
    return "{}: {}".format(event, summary)


def print_last_log(log_path: Path, label: str) -> int:
    """Print the last log line(s) for the monitor's checkup; returns 0 on success."""
    lines = last_log_line(log_path)
    if not lines:
        print("[{}] no log yet: {}".format(label, log_path), flush=True)
        return 0
    print("[{}] last {} log lines from {}".format(label, len(lines), log_path), flush=True)
    for line in lines:
        try:
            record = json.loads(line)
            print("  - {}", summarize_log_event(record), flush=True)
        except json.JSONDecodeError:
            print("  - {}", line, flush=True)
    return 0
def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tick", type=int, default=5,
                        help="Seconds between loop iterations (default 5).")
    parser.add_argument("--job-id", default=None,
                        help="Playlist job id; defaults to the first available job.")
    parser.add_argument("--model", default="openrouter/free",
                        help="OpenRouter model to run (default: openrouter/free).")
    parser.add_argument("--max-batches", type=int, default=None,
                        help="Stop after this many batches (default: run until complete).")
    parser.add_argument("--state", type=Path, default=Path("agent_state.json"),
                        help="State file path (default: agent_state.json).")
    parser.add_argument("--log", type=Path, default=None,
                        help="JSONL run log path (default: auto-created under agent_logs).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-iteration log output.")
    return parser.parse_args()


def run_agent_once(job_id, model, max_batches, state_path, log_path):
    """Run the agent once; return exit code (0 = ok)."""
    try:
        import openai  # noqa: F401
    except ImportError:
        print("[{}] OPENROUTER_API_KEY is not set; skipping agent run.".format(time.strftime("%H:%M:%S")), flush=True)
        return 0

    args = argparse.Namespace()
    args.job_id = job_id
    args.model = model
    args.batch_size = 1
    args.lookahead = 10
    args.context_chars = 4000
    args.max_batches = max_batches
    args.no_compact_context = False
    args.thought_tokens = 10000
    args.agent_mode = "thorough"
    args.max_turns = 15
    args.state = state_path
    args.log = log_path
    args.debug = False
    args.max_consecutive_incomplete = 3

    run_id = str(time.time())
    run_log = agent.RunLog(log_path, str(run_id))
    agent._RUN_LOG = run_log

    try:
        agent.main(args)
    except SystemExit as exc:
        if exc.code in (None, 130):
            return 0
        return int(exc.code) if isinstance(exc.code, int) else 1
    except Exception as exc:
        print("[{}] agent run error: {}: {}".format(time.strftime("%H:%M:%S"), type(exc).__name__, exc), flush=True)
        return 1
    return 0


def main():
    args = parse_args()

    if args.log is None:
        args.log = default_log_path()
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)

    print("[{}] agent_monitor_loop starting; tick={}s log={}".format(
        time.strftime("%H:%M:%S"), args.tick, args.log), flush=True)

    iteration = 0
    try:
        while True:
            iteration += 1
            run_agent_once(
                job_id=args.job_id,
                model=args.model,
                max_batches=args.max_batches,
                state_path=args.state,
                log_path=args.log,
            )
            if args.quiet:
                print("[{}] iteration={} ok".format(time.strftime("%H:%M:%S"), iteration), flush=True)
                continue
            print_last_log(args.log, "checkup-{}".format(iteration))
            print("[{}] sleeping {}s ...".format(time.strftime("%H:%M:%S"), args.tick), flush=True)
            # Exponential backoff on rate limits
            backoff_base = 5  # seconds
            backoff_cap = 60  # max seconds
            backoff = getattr("_monitor_backoff", 0, 0)
            if backoff > 0:
                print("[{}] backoff waiting {}s...".format(time.strftime("%H:%M:%S"), backoff), flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, backoff_cap)
            else:
                backoff = backoff_base
            _monitor_backoff = backoff
            time.sleep(args.tick)
    except KeyboardInterrupt:
        print("[{}] interrupted by user; exiting.".format(time.strftime("%H:%M:%S")), flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
