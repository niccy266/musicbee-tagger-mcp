#!/usr/bin/env python3
"""
Helper script to start an Nginx Docker container proxying port 80 to http://host.docker.internal:8000.
"""

import subprocess
import sys
from pathlib import Path

def main():
    container_name = "mcp-docs-proxy"
    conf_path = Path(__file__).parent.parent / "nginx.conf"

    print("[*] Stopping any existing mcp-docs-proxy container...")
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

    print("[*] Starting Nginx proxy container on port 80...")
    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "-p", "80:80",
        "-v", f"{conf_path}:/etc/nginx/nginx.conf:ro",
        "--add-host=host.docker.internal:host-gateway",
        "nginx:alpine"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("[!] Failed to start Docker container:", result.stderr)
        print("\nNote: Make sure Docker Desktop is running and port 80 is not in use by another service.")
        sys.exit(1)

    print("\n[+] Nginx Docker proxy started successfully!")
    print("[+] You can now access your documentation at: http://mcp-docs/home")
    print("\nTo stop the proxy later, run:")
    print(f"    docker rm -f {container_name}")

if __name__ == "__main__":
    main()
