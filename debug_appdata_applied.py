"""Show a sample of the pending changes in AppData staging dir."""
import json
from pathlib import Path

appdata_dir = Path(r"C:\Users\niccy\AppData\Roaming\musicbee-tagger-mcp\staged")
files = sorted(appdata_dir.glob("*.json"))
pending = []
for path in files:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (
            not manifest.get("applied", False)
            and not manifest.get("withdrawn", False)
            and not manifest.get("failed", False)
            and not manifest.get("archived", False)
        ):
            pending.append(manifest)
    except Exception:
        pass

print(f"Total pending: {len(pending)}")
print()
for m in pending[:5]:
    print(f"Stage ID: {m['stage_id']}")
    print(f"  File: {m.get('display_name')}")
    print(f"  Path: {m.get('absolute_path')}")
    print(f"  Created: {m.get('created_at')}")
    print(f"  MB score: {m.get('forensic_score')}")
    print(f"  Diff:")
    for d in m.get("diff", []):
        print(f"    {d['field']}: {d.get('old')} -> {d.get('new')}")
    print(f"  Notes: {m.get('notes', '')[:100]}")
    print()