#!/usr/bin/env python3
"""
Local Documentation Server for MusicBee Tagger MCP.
Builds MkDocs documentation and serves it locally, supporting http://mcp-docs/home.
"""

import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, HTTPServer
import webbrowser
from pathlib import Path

#!/usr/bin/env python3
"""
Local Documentation Server for MusicBee Tagger MCP.
Builds MkDocs documentation and serves it locally at http://mcp-docs:8000/home
without occupying port 80.
"""

import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, HTTPServer
import webbrowser
from pathlib import Path

PORT = 8000  # Non-privileged port to avoid port 80 conflicts

def build_docs():
    print("[*] Building documentation with MkDocs...")
    result = subprocess.run([sys.executable, "-m", "mkdocs", "build"], capture_output=True, text=True)
    if result.returncode != 0:
        print("[!] Error building MkDocs:", result.stderr)
        sys.exit(1)
    print("[+] MkDocs build successful.")

class DocsHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        site_dir = Path(__file__).parent.parent / "site"
        super().__init__(*args, directory=str(site_dir), **kwargs)

    def do_GET(self):
        # Normalize /home or /home/ to /index.html
        if self.path == "/home" or self.path == "/home/":
            self.path = "/index.html"
        elif self.path.startswith("/home/"):
            self.path = self.path[5:]  # strip /home prefix
        elif self.path == "/" or self.path == "":
            self.path = "/index.html"
        super().do_GET()

def run_server():
    build_docs()
    
    server = None
    try:
        server = HTTPServer(("127.0.0.1", PORT), DocsHandler)
    except Exception as e:
        print(f"[!] Failed to start HTTP server on port {PORT}: {e}")
        sys.exit(1)

    url = f"http://mcp-docs:{PORT}/home"
    print(f"\n[+] Documentation portal is running at: {url}")
    print(f"[+] Local folder: {Path(__file__).parent.parent / 'site'}")
    print("\nSetup instructions for clean local routing (no port 80 needed):")
    print("  1. Add '127.0.0.1 mcp-docs' to your hosts file:")
    print("     Windows: C:\\Windows\\System32\\drivers\\etc\\hosts")
    print("     macOS/Linux: /etc/hosts")
    print(f"  2. Open your browser and navigate to: {url}")
    print("Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down documentation server.")
        server.server_close()

if __name__ == "__main__":
    run_server()
