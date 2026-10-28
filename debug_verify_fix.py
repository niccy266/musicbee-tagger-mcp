"""Run list_pending with the APPDATA data directory to confirm 159 pending changes."""
import os
os.environ["MUSICBEE_TAGGER_DATA_DIR"] = r"C:\Users\niccy\AppData\Roaming\musicbee-tagger-mcp"

from musicbee_tagger_mcp.stage_manifest_store import StageManifestStore
store = StageManifestStore()
print(f"Directory: {store.directory}")
pending = store.list_pending()
print(f"Pending count: {len(pending)}")
print()
for p in pending[:5]:
    print(f"  stage_id: {p['stage_id']}")
    print(f"  file: {p['display_name']}")
    print(f"  created: {p['created_at']}")
    print()