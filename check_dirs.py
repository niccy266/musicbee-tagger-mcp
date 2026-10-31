import os
import sys

# Check both appdata and potential custom data dirs
appdata = os.environ.get("APPDATA", "")
custom_data_dir = os.environ.get("MUSICBEE_TAGGER_DATA_DIR", "")

dirs_to_check = []

if appdata:
    dirs_to_check.append(os.path.join(appdata, "musicbee-tagger-mcp"))

if custom_data_dir:
    dirs_to_check.append(custom_data_dir)
else:
    # Default data dir
    home = os.path.expanduser("~")
    dirs_to_check.append(os.path.join(home, "musicbee-tagger-mcp"))

for d in dirs_to_check:
    print(f"Checking directory: {d}")
    if os.path.exists(d):
        for subdir in ["playlists", "jobs", "registered", "staged"]:
            subdir_path = os.path.join(d, subdir)
            if os.path.exists(subdir_path):
                files = [f for f in os.listdir(subdir_path) if f.endswith(".json")]
                print(f"  {subdir}/: {len(files)} JSON files")
                if subdir == "playlists" and files:
                    # Show first few job summaries
                    import json
                    for f in sorted(files)[:3]:
                        path = os.path.join(subdir_path, f)
                        with open(path, 'r', encoding='utf-8') as fh:
                            job = json.load(fh)
                        tracks = job.get("tracks", [])
                        counts = {"pending": 0, "done": 0, "failed": 0}
                        for track in tracks:
                            status = track.get("status", "")
                            if status == "pending": counts["pending"] += 1
                            elif status == "done": counts["done"] += 1
                            elif status == "failed": counts["failed"] += 1
                        print(f"    {f[:20]}...: pending={counts['pending']}, done={counts['done']}, failed={counts['failed']}")
            else:
                print(f"  {subdir}/: directory not found")
    else:
        print(f"  Directory not found")