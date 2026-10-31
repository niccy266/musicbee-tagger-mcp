"""User-facing CLI for applying staged tag changes.

This is the ONLY code path that writes tags to audio files.
It is not exposed as an MCP tool and cannot be called by an agent.

Usage:
    python -m musicbee_tagger_mcp.apply_staged --stage-id <uuid>
    python -m musicbee_tagger_mcp.apply_staged --all
    python -m musicbee_tagger_mcp.apply_staged --all --dry-run
    python -m musicbee_tagger_mcp.apply_staged --list
    python -m musicbee_tagger_mcp.apply_staged --list-applied
    python -m musicbee_tagger_mcp.apply_staged --revert --stage-id <uuid>
    python -m musicbee_tagger_mcp.apply_staged --undo --stage-id <uuid>
"""

import argparse
import logging
import os
from pathlib import Path
import sys

from .staged_review import cmd_list, print_review, _print_diff
from .staged_apply import get_staged_applier
from .staging import get_staging_manager

from .staged_audit import audit_staged_changes as _audit_staged_changes


def cmd_audit(staging) -> None:
    report = _audit_staged_changes(staging.store)
    print(f"Audited {report['total_stages']} pending staged change(s).")
    print(report["score_scale"])
    print()
    if not report["flagged"]:
        print("No staged changes flagged for review.")
        return
    print(f"{report['flagged_count']} flagged for review:")
    for item in report["flagged"]:
        print(f"  stage_id   : {item['stage_id']}")
        print(f"  file       : {item['display_name']}")
        print(f"  flags      : {', '.join(item['flags'])}")
        if item.get("notes"):
            print(f"  reason     : {item['notes']}")
        print("  changes    :")
        _print_diff(item.get("diff_summary", []), include_title=False, indent="    ")
        print()



logger = logging.getLogger(__name__)


def cmd_apply_one(applier, stage_id: str, dry_run: bool, no_backup: bool) -> str:
    try:
        manifest = applier.load(stage_id)
    except FileNotFoundError:
        logger.error("Staged manifest %s is missing; skipping it.", stage_id)
        print(f"\n[ERROR] Stage {stage_id} is missing; moving to the next item.")
        return "missing_stage"
    if manifest.get("applied"):
        print(f"[SKIP] {stage_id} has already been applied.")
        return "already_applied"
    if manifest.get("withdrawn"):
        print(f"[SKIP] {stage_id} has been withdrawn.")
        return "withdrawn"
    if manifest.get("failed") or manifest.get("archived"):
        print(f"[SKIP] {stage_id} is {('failed' if manifest.get('failed') else 'archived')}.")
        return "failed" if manifest.get("failed") else "archived"

    display_name = manifest.get("display_name", stage_id)
    if not Path(manifest["absolute_path"]).is_file():
        applier.archive_missing_file(stage_id)
        logger.error(
            "Source audio file is missing; archived stage %s (%s).",
            stage_id,
            display_name,
        )
        print(f"\n[ARCHIVED] {display_name}: source file not found; moving to the next item.")
        return "archived"

    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()

    print()
    print_review(manifest, stage_id)

    if dry_run:
        print("\n[DRY RUN] No changes written.")
        return "dry_run"

    answer = input(
        "\nEnter=apply, n=mark failed and skip, a=defer to end, q=quit [Enter/n/a/q]: "
    ).strip().lower()
    if answer in {"n", "no"}:
        applier.mark_failed(stage_id, "Skipped by user during apply review.")
        logger.info("Marked stage %s (%s) failed at user request.", stage_id, display_name)
        print("[FAILED] Stored as failed; moving to the next item.")
        return "failed"
    if answer == "a":
        applier.defer(stage_id)
        logger.info("Deferred stage %s (%s) to the end of the review queue.", stage_id, display_name)
        print("[DEFERRED] Moved to the end of the staged review list.")
        return "deferred"
    if answer == "q":
        print("Quitting staged review.")
        return "quit"
    if answer not in {"", "y", "yes"}:
        print("Unrecognized choice; item left pending.")
        return "pending"

    try:
        result = applier.apply(stage_id, create_backup=not no_backup)
    except FileNotFoundError:
        applier.archive_missing_file(stage_id)
        logger.error(
            "Source audio file disappeared during apply; archived stage %s (%s).",
            stage_id,
            display_name,
        )
        print(f"\n[ARCHIVED] {display_name}: source file not found; moving to the next item.")
        return "archived"
    if result.get("status") == "withdrawn":
        print(f"\n[SKIP] {stage_id} was withdrawn before it could be applied.")
        return "withdrawn"
    fields = result.get("fields_written", [])
    backed_up = result.get("backup_created", False)
    print(f"\n✓ Applied {len(fields)} field(s): {', '.join(fields)}")
    if backed_up:
        print("  Backup created (.bak)")
    return "applied"


def cmd_revert_one(applier, stage_id: str) -> str:
    """Revert an applied staged change by restoring its .bak backup."""
    try:
        manifest = applier.load(stage_id)
    except FileNotFoundError:
        logger.error("Staged manifest %s is missing; cannot revert.", stage_id)
        print(f"\n[ERROR] Stage {stage_id} is missing.")
        return "missing_stage"
    if not manifest.get("applied"):
        status = []
        if manifest.get("reverted"):
            status.append("already reverted")
        if manifest.get("withdrawn"):
            status.append("withdrawn")
        if manifest.get("failed"):
            status.append("failed")
        if manifest.get("archived"):
            status.append("archived")
        print(f"\n[SKIP] {stage_id} is {', '.join(status) or 'not applied'}; cannot revert.")
        return "not_applied"
    backup_path = manifest.get("backup_path")
    if not backup_path:
        print(f"\n[SKIP] {stage_id} has no backup path stored; cannot revert.")
        return "no_backup"
    backup = Path(backup_path)
    if not backup.is_file():
        print(f"\n[ERROR] Backup file not found: {backup_path}; cannot revert.")
        return "no_backup_file"

    display_name = manifest.get("display_name", stage_id)
    print()
    print(f"Revert preview for {stage_id}:")
    print(f"  file: {display_name}")
    print(f"  backup: {backup_path}")
    print()
    print("This will restore the original .bak backup over the current file,")
    print("undoing all tag changes that were applied.")
    answer = input(
        "\nEnter=revert/restore backup, q=quit [Enter/q]: "
    ).strip().lower()
    if answer == "q":
        print("Quitting revert.")
        return "quit"
    if answer not in {"", "y", "yes"}:
        print("Unrecognized choice; revert aborted.")
        return "pending"

    try:
        result = applier.revert(stage_id)
    except FileNotFoundError as exc:
        logger.error("Revert failed for %s: %s", stage_id, exc)
        print(f"\n[ERROR] {exc}")
        return "error"
    if result.get("status") == "already_reverted":
        print(f"\n[SKIP] {stage_id} has already been reverted.")
        return "already_reverted"
    print(f"\n✓ Reverted {stage_id}: {display_name}")
    print(f"  Restored from backup: {backup_path}")
    return "reverted"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="python -m musicbee_tagger_mcp.apply_staged",
        description="Apply staged tag changes to audio files. "
                    "This is the only code path that writes tags.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage-id", metavar="UUID", help="Apply or revert a specific staged change.")
    group.add_argument("--all", action="store_true", help="Apply all pending staged changes.")
    group.add_argument("--list", action="store_true", help="List all pending staged changes.")
    group.add_argument("--audit", action="store_true", help="Audit pending staged changes for duplicates, conflicts, empty diffs, and low scores.")
    group.add_argument("--list-applied", action="store_true",
                       help="List all applied changes that can be reverted (have a .bak backup).")
    group.add_argument("--revert", action="store_true",
                       help="Revert an applied staged change by restoring its .bak backup.")
    group.add_argument("--undo", action="store_true",
                       help="Alias for --revert.")

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

    if args.audit:
        cmd_audit(staging)
        return

    if args.list_applied:
        applied = staging.store.list_applied_with_backup()
        if not applied:
            print("No applied changes with backups available for revert.")
            return
        print(f"{len(applied)} applied change(s) available for revert:\n")
        for entry in applied:
            print(f"  stage_id   : {entry['stage_id']}")
            print(f"  file       : {entry['display_name']}")
            if entry.get("applied_at"):
                print(f"  applied_at : {entry['applied_at']}")
            if entry.get("backup_path"):
                print(f"  backup     : {entry['backup_path']}")
            if entry.get("notes"):
                print(f"  reason     : {entry['notes']}")
            print(f"  changes    :")
            _print_diff(entry.get("diff_summary", []), include_title=False, indent="    ")
            print()
        return

    is_revert = args.revert or args.undo

    if args.stage_id:
        if is_revert:
            cmd_revert_one(applier, args.stage_id)
            return
        cmd_apply_one(applier, args.stage_id, dry_run=args.dry_run, no_backup=args.no_backup)
        return

    if args.all:
        if is_revert:
            print("ERROR: --revert/--undo requires --stage-id; cannot revert all at once.")
            return
        pending = staging.list_pending()
        if not pending:
            print("No pending staged changes.")
            return
        print(f"Found {len(pending)} pending change(s).\n")
        totals = {"applied": 0, "failed": 0, "deferred": 0, "archived": 0}
        for entry in pending:
            outcome = cmd_apply_one(
                applier,
                entry["stage_id"],
                dry_run=args.dry_run,
                no_backup=args.no_backup,
            )
            if outcome in totals:
                totals[outcome] += 1
            if outcome == "quit":
                break
        print(
            "\nReview summary: "
            f"{totals['applied']} applied, {totals['failed']} failed, "
            f"{totals['deferred']} deferred, {totals['archived']} archived."
        )


if __name__ == "__main__":
    main()
