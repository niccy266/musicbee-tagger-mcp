"""Debug script to check AppData staging directory."""
import json
from pathlib import Path

# Check the AppData default location
appdata_dir = Path(r"C:\Users\niccy\AppData\Roaming\musicbee-tagger-mcp\staged")
if not appdata_dir.exists():
    print(f"AppData staged directory does not exist: {appdata_dir}")
    print(f"Contents of parent: {[p.name for p in appdata_dir.parent.iterdir() if p.is_dir()]}")
else:
    files = sorted(appdata_dir.glob("*.json"))
    pending = []
    other = []
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
                other.append(manifest.get("stage_id", path.name))
        except Exception as e:
            print(f"ERROR reading {path.name}: {e}")
    print(f"AppData staged directory: {appdata_dir}")
    print(f"Total .json files: {len(files)}")
    print(f"Truly pending: {len(pending)}")
    print(f"Applied/other: {len(other)}")
    if pending:
        print("\n=== Pending changes ===")
        for sid in pending[:20]:
            print(f"  {sid}")

# Also check K:\tools location
tools_dir = Path(r"K:\tools\mcp-servers\musicbee-tags\data\staged")
if tools_dir.exists():
    files2 = sorted(tools_dir.glob("*.json"))
    pending2 = []
    for path in files2:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if (
                not manifest.get("applied", False)
                and not manifest.get("withdrawn", False)
                and not manifest.get("failed", False)
                and not manifest.get("archived", False)
            ):
                pending2.append(manifest.get("stage_id", path.name))
        except Exception:
            pass
    print(f"\nK:\\tools staged directory: {tools_dir}")
    print(f"Total .json files: {len(files2)}")
    print(f"Truly pending: {len(pending2)}")