import sys
sys.path.insert(0, "K:\\dev\\vibe-coding\\musicbee-mcp-server\\src")

from musicbee_tagger_mcp.job_store import get_job_store

jobs = get_job_store().list_jobs()
print(f"Returned {len(jobs)} jobs")
if jobs:
    print("First job:", jobs[0])
    # Check what keys are available
    print("Keys in first job:", list(jobs[0].keys()))