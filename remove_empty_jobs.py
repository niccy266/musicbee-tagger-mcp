import json
import os
import shutil

data_dir = r"C:\Users\niccy\AppData\Roaming\musicbee-tagger-mcp\playlists"
if not os.path.exists(data_dir):
    print(f"Directory not found: {data_dir}")
    exit(1)

files = sorted([f for f in os.listdir(data_dir) if f.endswith(".json")])
print(f"Found {len(files)} job files in playlists directory")

removed = 0
kept = 0

for f in files:
    path = os.path.join(data_dir, f)
    with open(path, 'r', encoding='utf-8') as fh:
        job = json.load(fh)
    tracks = job.get("tracks", [])
    counts = {"pending": 0, "done": 0, "failed": 0, "skipped": job.get("skipped", 0)}
    for track in tracks:
        status = track.get("status", "")
        if status in counts:
            counts[status] = counts.get(status, 0) + 1
    
    # Check if job is empty (no pending, no done, no failed tracks)
    is_empty = counts["pending"] == 0 and counts["done"] == 0 and counts["failed"] == 0
    
    if is_empty:
        # Remove the empty job file
        os.remove(path)
        removed += 1
        print(f"Removed empty job: {f[:20]}... - {job.get('playlist_name', 'unknown')}")
    else:
        kept += 1

print(f"\nRemoved {removed} empty jobs")
print(f"Kept {kept} jobs with work")