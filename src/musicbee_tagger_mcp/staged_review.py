"""Terminal rendering for staged tag reviews."""

import re
import os
import sys
from urllib.parse import quote

from wcwidth import wcswidth

from .metadata_reader import read_audio_metadata

_CONTROLS = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)
_COLUMN_WIDTHS = (16, 26, 26)


def _wrap_cell(value: str, width: int) -> list[str]:
    """Wrap text by terminal display width, including wide Unicode glyphs."""
    words = value.split()
    lines = []
    current = ""
    for word in words:
        word_width = wcswidth(word)
        current_width = wcswidth(current)
        if current and current_width + 1 + word_width <= width:
            current += " " + word
            continue
        if current:
            lines.append(current)
            current = ""
        while wcswidth(word) > width:
            piece = ""
            for char in word:
                if piece and wcswidth(piece + char) > width:
                    break
                piece += char
            lines.append(piece)
            word = word[len(piece):]
        current = word
    if current or not lines:
        lines.append(current)
    return lines


def _render_table(rows: list[tuple[str, str, str]]) -> str:
    """Render a fixed-width 80-column review table."""
    widths = _COLUMN_WIDTHS
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    header_border = "+" + "+".join("=" * (width + 2) for width in widths) + "+"
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ

    def paint(value: str, code: str) -> str:
        return f"\x1b[{code}m{value}\x1b[0m" if color else value

    output = [border]

    def render_row(values, header=False):
        wrapped = [_wrap_cell(str(value), width) for value, width in zip(values, widths)]
        height = max(map(len, wrapped))
        for line_number in range(height):
            cells = []
            for column, width in enumerate(widths):
                value = wrapped[column][line_number] if line_number < len(wrapped[column]) else ""
                if header:
                    value = paint(value, "1;36")
                elif column == 0:
                    value = paint(value, "1;33")
                elif column == 1:
                    value = paint(value, "31")
                elif value.strip() == "(no change)":
                    value = paint(value, "2;37")
                else:
                    value = paint(value, "32")
                cells.append(" " + value + " " * (width - wcswidth(
                    wrapped[column][line_number]
                    if line_number < len(wrapped[column]) else ""
                )) + " ")
            output.append("|" + "|".join(cells) + "|")

    render_row(("Field", "Original", "Proposed"), header=True)
    output.append(header_border)
    for row in rows:
        render_row(row)
        output.append(border)
    return "\n".join(output)


def _display_value(value) -> str:
    if value is None or value == "":
        return "(empty)"
    return _CONTROLS.sub(
        lambda match: f"\\u{ord(match.group()):04x}", str(value)
    )


def _print_diff(diff, original_title=None, proposed_title=None, *,
                include_title=True, indent="  ", required_fields=(),
                original_tags=None) -> None:
    original_tags = original_tags or {}
    changes = {item.get("field", "?"): item for item in diff}
    required = set(required_fields)
    rows = {}
    for field in required_fields:
        change = changes.get(field)
        if change is None:
            rows[field] = (original_tags.get(field), "(no change)")
        else:
            rows[field] = (change.get("old"), change.get("new"))
    if include_title and "title" not in required:
        rows["title"] = (original_title, proposed_title)
    rows.update({
        item.get("field", "?"): (item.get("old"), item.get("new"))
        for item in diff
        if item.get("field") not in required
        and (item.get("field") != "title" or not include_title)
    })
    table = [(field, _display_value(old), _display_value(new))
             for field, (old, new) in rows.items()]
    if not table:
        print(f"{indent}(no changes)")
        return
    rendered = _render_table(table)
    print("\n".join(indent + line for line in rendered.splitlines()))


def print_review(manifest: dict, stage_id: str) -> None:
    release_id = manifest.get("mb_release_id")
    try:
        original_tags = read_audio_metadata(manifest["absolute_path"])["tags"]
    except Exception:
        original_tags = {}
    title = original_tags.get("title")
    proposed_title = manifest.get("proposed_tags", {}).get("title", title)
    print("Proposed changes:")
    _print_diff(
        manifest.get("diff", []), title, proposed_title,
        required_fields=("artist", "title", "album"),
        original_tags=original_tags,
    )
    print(f"\nOriginal title: {_display_value(title)}")
    print(f"File           : {manifest['display_name']}")
    print(f"Stage ID       : {stage_id}")
    notes = manifest.get("notes", "")
    if notes:
        print(f"\nReason: {notes}")
    score = manifest.get("forensic_score")
    if score is not None:
        print(f"MusicBrainz score: {score:.1f}")
    if release_id:
        release_id = str(release_id)
        release_url = f"https://musicbrainz.org/release/{quote(release_id, safe='')}"
        print(f"MusicBrainz release ID: {release_id}")
        print(f"MusicBrainz release:    {release_url}")
    else:
        print("MusicBrainz release ID: (not set)")


def cmd_list(staging) -> None:
    pending = staging.list_pending()
    if not pending:
        print("No pending staged changes.")
        return
    print(f"{len(pending)} pending staged change(s):\n")
    for entry in pending:
        print(f"  stage_id   : {entry['stage_id']}")
        print(f"  file       : {entry['display_name']}")
        print(f"  created    : {entry['created_at']}")
        if (score := entry.get("forensic_score")) is not None:
            print(f"  MB score   : {score:.1f}")
        if (notes := entry.get("notes")):
            print(f"  reason     : {notes}")
        print("  changes    :")
        _print_diff(entry.get("diff_summary", []), include_title=False, indent="    ")
        print()
