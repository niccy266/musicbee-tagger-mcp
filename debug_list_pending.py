"""Debug script to find which staged files fail to load in list_pending()."""
import json
from pathlib import Path

staging_dir = Path(r"K:\tools\mcp-servers\musicbee-tags\data\staged")
files = sorted(staging_dir.glob("*.json"))
pending = []
skipped = []
errors = []

for path in files:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (
            not manifest.get("applied", False)
            and not manifest.get("withdrawn", False)
            and not manifest.get("failed", False)
            and not manifest.get("archived", False)
        ):
            pending.append(manifest.get("stage_id", path.name))
        else:
            skipped.append(manifest.get("stage_id", path.name))
    except Exception as e:
        errors.append((path.name, str(e)))

print(f"Total .json files: {len(files)}")
print(f"Pending (unapplied): {len(pending)}")
print(f"Skipped (applied/withdrawn/failed/archived): {len(skipped)}")
print(f"Errors (silently skipped by list_pending): {len(errors)}")

if errors:
    print("\n=== First 5 errors ===")
    for name, err in errors[:5]:
        print(f"  {name}: {err[:100]}")

if pending:
    print(f"\n=== First 10 pending ===")
    for sid in pending[:10]:
        print(f"  {sid}")