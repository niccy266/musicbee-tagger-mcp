"""User-facing CLI for applying staged tag changes.

This is the ONLY code path that writes tags to audio files.
It is not exposed as an MCP tool and cannot be called by an agent.

Usage:
    python -m musicbee_tagger_mcp.apply_staged --stage-id <uuid>
    python -m musicbee_tagger_mcp.apply_staged --all
    python -m musicbee_tagger_mcp.apply_staged --all --dry-run
    python -m musicbee_tagger_mcp.apply_staged --list
"""

import argparse
from urllib.parse import quote

from .metadata_reader import read_audio_metadata
from .staged_apply import get_staged_applier
from .staging import get_staging_manager


def _display_value(value) -> str:
    if value is None or value == "":
        return "(empty)"
    return str(value).replace("\r", " ").replace("\n", " ")


def _print_diff(
    diff: list,
    original_title=None,
    proposed_title=None,
    *,
    include_title: bool = True,
    indent: str = "  ",
) -> None:
    """Render staged fields as an aligned original/proposed table."""
    rows = {"title": (original_title, proposed_title)} if include_title else {}
    rows.update({
        change.get("field", "?"): (change.get("old"), change.get("new"))
        for change in diff
        if change.get("field") != "title" or not include_title
    })
    # Keep the source title in every review, including proposals that do not
    # change it. The title values are read from the file at review time.
    table = [(field, _display_value(old), _display_value(new))
             for field, (old, new) in rows.items()]
    if not table:
        print(f"{indent}(no changes)")
        return
    headers = ("Field", "Original", "Proposed")
    widths = [max(len(headers[i]), *(len(row[i]) for row in table))
              for i in range(3)]

    def line(left, middle, right, fill="-"):
        return left + middle.join(fill * (width + 2) for width in widths) + right

    print(indent + line("+", "+", "+"))
    print(indent + "| " + " | ".join(headers[i].ljust(widths[i])
                                       for i in range(3)) + " |")
    print(indent + line("+", "+", "+"))
    for row in table:
        print(indent + "| " + " | ".join(row[i].ljust(widths[i])
                                           for i in range(3)) + " |")
    print(indent + line("+", "+", "+"))


def _print_review(manifest: dict, stage_id: str) -> None:
    release_id = manifest.get("mb_release_id")
    if release_id:
        release_id = str(release_id)
        release_url = f"https://musicbrainz.org/release/{quote(release_id, safe='')}"
        print(f"MusicBrainz release ID: {release_id}")
        print(f"MusicBrainz release:    {release_url}")
    else:
        print("MusicBrainz release ID: (not set)")

    try:
        original_title = read_audio_metadata(manifest["absolute_path"])["tags"].get("title")
    except Exception:
        original_title = None
    proposed_tags = manifest.get("proposed_tags", {})
    proposed_title = proposed_tags.get("title", original_title)

    print(f"Original title: {_display_value(original_title)}")
    print(f"File           : {manifest['display_name']}")
    print(f"Stage ID       : {stage_id}")
    score = manifest.get("forensic_score")
    if score is not None:
        print(f"MusicBrainz score: {score:.1f}")
    print("\nProposed changes:")
    _print_diff(manifest.get("diff", []), original_title, proposed_title)


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
        score = entry.get("forensic_score")
        if score is not None:
            print(f"  MB score   : {score:.1f}")
        print(f"  changes    :")
        _print_diff(entry.get("diff_summary", []), include_title=False, indent="    ")
        print()


def cmd_apply_one(applier, stage_id: str, dry_run: bool, no_backup: bool) -> None:
    manifest = applier.load(stage_id)
    if manifest.get("applied"):
        print(f"[SKIP] {stage_id} has already been applied.")
        return

    print()
    _print_review(manifest, stage_id)

    if dry_run:
        print("\n[DRY RUN] No changes written.")
        return

    answer = input("\nApply these changes? [y/N] ").strip().lower()
    if answer != "y":
        print("Skipped.")
        return

    result = applier.apply(stage_id, create_backup=not no_backup)
    fields = result.get("fields_written", [])
    backed_up = result.get("backup_created", False)
    print(f"\n✓ Applied {len(fields)} field(s): {', '.join(fields)}")
    if backed_up:
        print("  Backup created (.bak)")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m musicbee_tagger_mcp.apply_staged",
        description="Apply staged tag changes to audio files. "
                    "This is the only code path that writes tags.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage-id", metavar="UUID", help="Apply a specific staged change.")
    group.add_argument("--all", action="store_true", help="Apply all pending staged changes.")
    group.add_argument("--list", action="store_true", help="List all pending staged changes.")

    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be applied without writing anything.")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip creating .bak backup files before writing.")

    args = parser.parse_args()
    staging = get_staging_manager()
    applier = get_staged_applier()

    if args.list:
        cmd_list(staging)
        return

    if args.stage_id:
        cmd_apply_one(applier, args.stage_id, dry_run=args.dry_run, no_backup=args.no_backup)
        return

    if args.all:
        pending = staging.list_pending()
        if not pending:
            print("No pending staged changes.")
            return
        print(f"Found {len(pending)} pending change(s).\n")
        for entry in pending:
            cmd_apply_one(
                applier,
                entry["stage_id"],
                dry_run=args.dry_run,
                no_backup=args.no_backup,
            )


if __name__ == "__main__":
    main()
