#!/usr/bin/env python
"""Fix the _print_jobs function in server.py to correctly display job status."""

import re

filepath = "K:\\dev\\vibe-coding\\musicbee-mcp-server\\src\\musicbee_tagger_mcp\\server.py"

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# The old pattern to replace
old_pattern = """def _print_jobs() -> None:
    try:
        jobs = get_job_store().list_jobs()
    except RuntimeError as error:
        print(f"Unable to list playlist jobs: {error}")
        return
    if not jobs:
        print("No playlist jobs with pending work.")
        return
    print(f"{len(jobs)} playlist job(s) with pending work:")
    for job in jobs:
        print(
            f"  {job.get('job_id')} - {job.get('playlist_name', '')} \""
            f"({job.get('pending', 0)} pending, "
            f"{job.get('completed', 0)} completed)\"\n
        )"""

# The new pattern
new_pattern = """def _print_jobs() -> None:
    try:
        jobs = get_job_store().list_jobs()
    except RuntimeError as error:
        print(f"Unable to list playlist jobs: {error}")
        return
    if not jobs:
        print("No playlist jobs with pending work.")
        return
    print(f"{len(jobs)} playlist job(s) with pending work:")
    for job in jobs:
        counts = job.get("counts", {})
        pending = counts.get("pending", 0)
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        completed = done + failed
        print(
            f"  {job.get('job_id')} - {job.get('playlist_name', '')} \""
            f"({pending} pending, "
            f"{completed} completed)\"\n
        )"""

if old_pattern in content:
    content = content.replace(old_pattern, new_pattern)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed _print_jobs function in server.py")
else:
    print("Could not find the target pattern in server.py")
    # Let's print what we have around line 41-56
    lines = content.split('\n')
    for i in range(40, 57):
        print(f"{i+1}: {lines[i]}")