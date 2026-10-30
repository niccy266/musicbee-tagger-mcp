import json
import os

data_dir = r"C:\Users\niccy\AppData\Roaming\musicbee-tagger-mcp\playlists"
if not os.path.exists(data_dir):
    print(f"Directory not found: {data_dir}")
    exit(1)

files = sorted([f for f in os.listdir(data_dir) if f.endswith(".json")])
print(f"Found {len(files)} job files in playlists directory")

pending_jobs = []
done_jobs = []
failed_jobs = []
empty_jobs = []

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
    
    if counts["pending"] > 0:
        pending_jobs.append((f, job.get("playlist_name"), counts))
    elif counts["done"] > 0 or counts["failed"] > 0:
        failed_jobs.append((f, job.get("playlist_name"), counts))
    else:
        empty_jobs.append((f, job.get("playlist_name"), counts))

print(f"\nPending jobs (pending > 0): {len(pending_jobs)}")
for f, name, counts in pending_jobs:
    print(f"  {f[:8]}... - {name}: {counts}")

print(f"\nFailed jobs (done/failed > 0, pending=0): {len(failed_jobs)}")
for f, name, counts in failed_jobs:
    print(f"  {f[:8]}... - {name}: {counts}")

print(f"\nEmpty jobs (no tracks): {len(empty_jobs)}")
for f, name, counts in empty_jobs:
    print(f"  {f[:8]}... - {name}: {counts}")