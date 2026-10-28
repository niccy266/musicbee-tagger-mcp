"""Check the StrangeTags playlist status breakdown."""
import json
from collections import Counter

p = json.load(open(r"C:\Users\niccy\AppData\Roaming\musicbee-tagger-mcp\playlists\5642052b-022f-4b0a-a8cb-f60448279ea0.json", encoding="utf-8"))
tracks = p.get("tracks", [])
c = Counter(t.get("status") for t in tracks)
print(f"Playlist: {p.get('playlist_name')}")
print(f"Total tracks: {len(tracks)}")
print(f"Status breakdown: {dict(c)}")
print()
# Show some failed tracks
failed = [t for t in tracks if t.get("status") == "failed" and t.get("error")]
print(f"Failed with errors: {len(failed)}")
for t in failed[:5]:
    print(f"  {t['display_name'][:80]}")
    print(f"    Error: {t['error'][:120]}")