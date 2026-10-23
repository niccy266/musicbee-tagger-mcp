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
import json
import sys
from pathlib import Path

from .staging import get_staging_manager


def _print_diff(diff: list, indent: str = "  ") -> None:
    if not diff:
        print(f"{indent}(no changes)")
        return
    for change in diff:
        field = change.get("field", "?")
        old = change.get("old")
        new = change.get("new")
        old_str = repr(old) if old is not None else "(empty)"
        new_str = repr(new) if new is not None else "(empty)"
        print(f"{indent}{field}:")
        print(f"{indent}  - {old_str}")
        print(f"{indent}  + {new_str}")


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
        _print_diff(entry.get("diff_summary", []), indent="    ")
        print()


def cmd_apply_one(staging, stage_id: str, dry_run: bool, no_backup: bool) -> None:
    manifest = staging.load(stage_id)
    if manifest.get("applied"):
        print(f"[SKIP] {stage_id} has already been applied.")
        return

    print(f"\nFile    : {manifest['display_name']}")
    print(f"Stage ID: {stage_id}")
    score = manifest.get("forensic_score")
    if score is not None:
        print(f"MB Score: {score:.1f}")
    print("\nProposed changes:")
    _print_diff(manifest.get("diff", []))

    if dry_run:
        print("\n[DRY RUN] No changes written.")
        return

    answer = input("\nApply these changes? [y/N] ").strip().lower()
    if answer != "y":
        print("Skipped.")
        return

    result = staging.apply(stage_id, create_backup=not no_backup)
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

    if args.list:
        cmd_list(staging)
        return

    if args.stage_id:
        cmd_apply_one(staging, args.stage_id, dry_run=args.dry_run, no_backup=args.no_backup)
        return

    if args.all:
        pending = staging.list_pending()
        if not pending:
            print("No pending staged changes.")
            return
        print(f"Found {len(pending)} pending change(s).\n")
        for entry in pending:
            cmd_apply_one(
                staging,
                entry["stage_id"],
                dry_run=args.dry_run,
                no_backup=args.no_backup,
            )


if __name__ == "__main__":
    main()
