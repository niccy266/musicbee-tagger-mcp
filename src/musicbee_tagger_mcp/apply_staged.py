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

from .staged_review import cmd_list, print_review
from .staged_apply import get_staged_applier
from .staging import get_staging_manager


def cmd_apply_one(applier, stage_id: str, dry_run: bool, no_backup: bool) -> None:
    manifest = applier.load(stage_id)
    if manifest.get("applied"):
        print(f"[SKIP] {stage_id} has already been applied.")
        return
    if manifest.get("withdrawn"):
        print(f"[SKIP] {stage_id} has been withdrawn.")
        return

    print()
    print_review(manifest, stage_id)

    if dry_run:
        print("\n[DRY RUN] No changes written.")
        return

    answer = input("\nApply these changes? [y/N] ").strip().lower()
    if answer != "y":
        print("Skipped.")
        return

    result = applier.apply(stage_id, create_backup=not no_backup)
    if result.get("status") == "withdrawn":
        print(f"\n[SKIP] {stage_id} was withdrawn before it could be applied.")
        return
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
