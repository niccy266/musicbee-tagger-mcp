"""Tests for the AI Supervisor agent monitor in scripts/ai_supervised_agent_loop.py."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ai_supervised_agent_loop import AISupervisor


def test_ai_supervisor_loop_detection():
    supervisor = AISupervisor()
    tool_call = {
        "id": "call-1",
        "function": {
            "name": "search_canonical_release",
            "arguments": json.dumps({"artist": "Test", "title": "Song"})
        }
    }
    msg = {"role": "assistant", "content": "Searching...", "tool_calls": [tool_call]}

    # Send identical tool calls 3 times
    advice1 = supervisor.evaluate_turn(msg)
    advice2 = supervisor.evaluate_turn(msg)
    advice3 = supervisor.evaluate_turn(msg)

    assert advice1 is None
    assert advice2 is None
    assert advice3 is not None
    assert "Loop Detected" in advice3
    assert "stage_tag_changes" in advice3


def test_ai_supervisor_low_score_frustration():
    supervisor = AISupervisor()
    msg = {"role": "assistant", "content": "Trying to find a match...", "tool_calls": []}
    
    # Simulate low score tool results
    tool_results = [
        {"role": "tool", "content": json.dumps({"forensic_score": 45.0})},
        {"role": "tool", "content": json.dumps({"forensic_score": 50.0})},
    ]

    advice = supervisor.evaluate_turn(msg, tool_results=tool_results)
    assert advice is not None
    assert "Low Match Frustration" in advice
    assert "reviewed and adjusted later" in advice
