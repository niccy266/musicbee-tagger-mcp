"""Stateless text investigation tools."""

from typing import Any, Dict

from ..mojibake import fix_mojibake


def repair_mojibake(text: str) -> Dict[str, Any]:
    """Detect and suggest repairs for common mojibake patterns."""
    return fix_mojibake(text)


def register_text_tools(app) -> None:
    app.tool()(repair_mojibake)
