#!/usr/bin/env python
"""Show playlist jobs in a nice table format with all statuses."""
import json
import os
import sys

sys.path.insert(0, r"K:\dev\vibe-coding\musicbee-mcp-server\src")
from musicbee_tagger_mcp.job_store import get_job_store

# All possible statuses from job_store.py
STATUSES = ("pending", "in_progress", "done", "failed", "skipped", "unresolved", "needs_review", "partial")

# Get all jobs
jobs = get_job_store().list_jobs()

# Print table header
header = f"{'Job ID':<36} {'Playlist':<20} " + " ".join(f"{s:>12}" for s in STATUSES) + "  Total"
print(header)
print("-" * len(header))

for job in jobs:
    counts = job.get("counts", {})
    # Count each status
    row_counts = {}
    total = 0
    for status in STATUSES:
        count = counts.get(status, 0)
        row_counts[status] = count
        total += count
    
    job_id = job.get("job_id", "")[:35]
    playlist = job.get("playlist_name", "")[:19]
    
    # Format: job_id, playlist, then counts for each status, then total
    row = f"{job_id:<36} {playlist:<20} " + " ".join(f"{row_counts[s]:>12}" for s in STATUSES) + f"  {total:>5}"
    print(row)

# Print summary
print(f"\nTotal jobs shown: {len(jobs)}")
print(f"Total tracks across all jobs: {sum(sum(j.get('counts', {}).values()) for j in jobs)}")