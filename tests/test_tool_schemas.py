"""Regression test: no MCP tool schema requires a catch-all 'kwargs' field."""

import asyncio
import sys
from pathlib import Path

# Ensure src/ is importable (mirrors conftest.py)
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_no_tool_requires_kwargs():
    """Ensure no registered tool declares 'kwargs' as a required parameter.

    In mcp >= 2.0, a `**kwargs: Any` signature on the tool function is reflected
    as a required `kwargs` field in the JSON schema. This makes the schema
    unusable because clients must send an opaque `kwargs` dict instead of
    explicit arguments. All tool functions must use explicit parameters.
    """
    from musicbee_tagger_mcp.server import app

    tools = asyncio.run(app.list_tools())
    bad_tools = []
    for tool in tools:
        required = tool.input_schema.get("required", []) or []
        if "kwargs" in required:
            bad_tools.append((tool.name, required, tool.input_schema.get("properties", {}).keys()))

    assert not bad_tools, (
        "The following MCP tools still have 'kwargs' as a required field in their schema:\n"
        + "\n".join(f"  - {name}: required={req}, properties={list(props)}" for name, req, props in bad_tools)
    )