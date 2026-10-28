#!/bin/sh
# Entrypoint for the musicbee-mcp container.
#
# Fixes ownership on mounted volumes, generates self-signed certs if missing,
# then launches the HTTPS MCP server wrapper.

set -eu

# Ensure /staging and /data are writable by mcpuser (uid 10001).
if [ -d /staging ]; then chown -R mcpuser:mcpuser /staging 2>/dev/null || true; fi
if [ -d /data ]; then chown -R mcpuser:mcpuser /data 2>/dev/null || true; fi
if [ -d /certs ]; then chown -R mcpuser:mcpuser /certs 2>/dev/null || true; fi

# Generate self-signed TLS certificate if not already present (via the Python script).
# The https_mcp_server.py script generates certs on first start.

# Drop privileges to mcpuser and run the HTTPS MCP server.
exec python scripts/https_mcp_server.py