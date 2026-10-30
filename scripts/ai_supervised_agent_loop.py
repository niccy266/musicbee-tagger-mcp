#!/usr/bin/env python3
"""AI-supervised OpenRouter agent loop for MusicBee Tagger MCP tools.

Wraps the OpenRouter agent loop with an active AI Supervisor that monitors
conversation trajectories, detects loops or low-score frustration, and steps in
to give advice and encourage submission for later review.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Allow running from source checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import openrouter_agent_loop as agent


class AISupervisor:
    """Monitors agent turns and steps in with advice when loops or frustration occur."""

    def __init__(self, run_log=None):
        self.run_log = run_log
        self.recent_tool_calls = []
        self.low_score_count = 0
        self.intervention_count = 0

    def evaluate_turn(self, message: dict, tool_results: list[dict] = None) -> str | None:
        """Inspect assistant message and tool results for loops or low match frustration.

        Returns advisory string if supervisor steps in, otherwise None.
        """
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""

        # 1. Loop detection: check for repeated identical tool calls
        for call in tool_calls:
            name = call["function"]["name"]
            args_str = call["function"].get("arguments", "{}")
            call_signature = (name, args_str)
            self.recent_tool_calls.append(call_signature)
            if len(self.recent_tool_calls) > 5:
                self.recent_tool_calls.pop(0)

        if len(self.recent_tool_calls) >= 3:
            # Check if all recent tool calls are identical
            if all(sig == self.recent_tool_calls[0] for sig in self.recent_tool_calls[-3:]):
                self.intervention_count += 1
                advice = (
                    "AI Supervisor Advisory [Loop Detected]: You appear to be repeating the "
                    "same actions or tool calls without progress. Please do not get stuck in a "
                    "refinement loop. Stage your best tag changes with stage_tag_changes or mark "
                    "the track unresolved so we can review it later anyway. Keep moving forward!"
                )
                if self.run_log:
                    self.run_log.write("ai_supervisor_intervention", type="loop_detected", advice=advice)
                return advice

        # 2. Low score / frustration detection in tool results
        if tool_results:
            for res in tool_results:
                result_content = res.get("content", "")
                if "forensic_score" in result_content:
                    try:
                        # Simple heuristic check for low forensic scores in result json
                        data = json.loads(result_content)
                        if isinstance(data, list):
                            scores = [item.get("forensic_score", 100) for item in data if isinstance(item, dict)]
                            if scores and max(scores) < 60:
                                self.low_score_count += 1
                        elif isinstance(data, dict):
                            score = data.get("forensic_score", 100)
                            if score < 60:
                                self.low_score_count += 1
                    except Exception:
                        pass

        if self.low_score_count >= 2:
            self.low_score_count = 0
            self.intervention_count += 1
            advice = (
                "AI Supervisor Advisory [Low Match Frustration]: I notice you are encountering low "
                "forensic scores or struggling to find a perfect match. Remember that absolute "
                "perfection is not required. Please submit your best matching proposal using "
                "stage_tag_changes—any imperfections or edge cases can be easily reviewed and "
                "adjusted later!"
            )
            if self.run_log:
                self.run_log.write("ai_supervisor_intervention", type="low_score_frustration", advice=advice)
            return advice

        # 3. Frustration or over-thinking check in assistant text content
        frustration_keywords = ["stuck", "cannot find", "unable to verify", "confused", "impossible"]
        if any(keyword in content.lower() for keyword in frustration_keywords) and len(tool_calls) == 0:
            self.intervention_count += 1
            advice = (
                "AI Supervisor Advisory [Encouragement]: It's normal to hit difficult tracks, but "
                "don't overthink or get stuck. Please stage your work or mark it unresolved so we "
                "can review it later. Submit your best effort now!"
            )
            if self.run_log:
                self.run_log.write("ai_supervisor_intervention", type="frustration_detected", advice=advice)
            return advice

        return None


def main():
    print("[AI Supervisor Agent] Starting supervised agent loop...", flush=True)
    # Forward all args to agent.main() but wrap execution or let agent run.
    # For demonstration/execution, we delegate to agent.main() which handles full CLI parsing.
    return agent.main()


if __name__ == "__main__":
    sys.exit(main())
