"""List top 20 applied changes sorted by forensic score."""
import sys
sys.path.insert(0, "src")

from musicbee_tagger_mcp.stage_manifest_store import StageManifestStore
from pathlib import Path

# The agent applies to K:\tools\mcp-servers\musicbee-tags\data\staged
staging_dir = Path(r"K:\tools\mcp-servers\musicbee-tags\data\staged")
store = StageManifestStore(staging_dir)
applied = store.list_applied_with_backup()

# Sort by forensic_score descending, then by applied_at
applied.sort(key=lambda x: ((x.get("forensic_score") or 0), x.get("applied_at") or ""), reverse=True)

print(f"Total applied with backup: {len(applied)}")
print(f"Showing top 20 by forensic score:")
print()

for i, entry in enumerate(applied[:20], 1):
    score = entry.get("forensic_score")
    print(f"{i:2d}. {entry['display_name']}")
    print(f"    stage_id: {entry['stage_id']}")
    print(f"    MB score: {score if score is not None else 'N/A'}")
    print(f"    applied_at: {entry.get('applied_at', 'N/A')}")
    print(f"    backup: {entry.get('backup_path', 'N/A')}")
    if entry.get("notes"):
        print(f"    reason: {entry['notes'][:100]}")
    print()