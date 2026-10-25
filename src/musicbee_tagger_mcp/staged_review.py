"""Terminal rendering for staged tag reviews."""

import re
from urllib.parse import quote

from tabulate import tabulate

from .metadata_reader import read_audio_metadata

_CONTROLS = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)


def _display_value(value) -> str:
    if value is None or value == "":
        return "(empty)"
    return _CONTROLS.sub(
        lambda match: f"\\u{ord(match.group()):04x}", str(value)
    )


def _print_diff(diff, original_title=None, proposed_title=None, *,
                include_title=True, indent="  ") -> None:
    rows = {"title": (original_title, proposed_title)} if include_title else {}
    rows.update({
        item.get("field", "?"): (item.get("old"), item.get("new"))
        for item in diff
        if item.get("field") != "title" or not include_title
    })
    table = [(field, _display_value(old), _display_value(new))
             for field, (old, new) in rows.items()]
    if not table:
        print(f"{indent}(no changes)")
        return
    rendered = tabulate(
        table, headers=("Field", "Original", "Proposed"), tablefmt="grid",
        maxcolwidths=[16, 24, 24], disable_numparse=True,
    )
    print("\n".join(indent + line for line in rendered.splitlines()))


def print_review(manifest: dict, stage_id: str) -> None:
    release_id = manifest.get("mb_release_id")
    if release_id:
        release_id = str(release_id)
        release_url = f"https://musicbrainz.org/release/{quote(release_id, safe='')}"
        print(f"MusicBrainz release ID: {release_id}")
        print(f"MusicBrainz release:    {release_url}")
    else:
        print("MusicBrainz release ID: (not set)")

    try:
        title = read_audio_metadata(manifest["absolute_path"])["tags"].get("title")
    except Exception:
        title = None
    proposed_title = manifest.get("proposed_tags", {}).get("title", title)
    print(f"Original title: {_display_value(title)}")
    print(f"File           : {manifest['display_name']}")
    print(f"Stage ID       : {stage_id}")
    score = manifest.get("forensic_score")
    if score is not None:
        print(f"MusicBrainz score: {score:.1f}")
    print("\nProposed changes:")
    _print_diff(manifest.get("diff", []), title, proposed_title)


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
        print("  changes    :")
        _print_diff(entry.get("diff_summary", []), include_title=False, indent="    ")
        print()
