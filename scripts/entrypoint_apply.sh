#!/bin/sh
# Entrypoint for the musicbee-apply container.
#
# Fixes ownership on mounted volumes, then sleeps.
# This container is triggered by a secret user command via:
#   docker compose exec musicbee-apply musicbee-tagger-apply --all
#
# It does not run any long-lived service.

set -eu

if [ -d /staging ]; then chown -R applyuser:applyuser /staging 2>/dev/null || true; fi
if [ -d /data ]; then chown -R applyuser:applyuser /data 2>/dev/null || true; fi
if [ -d /audio ]; then chown -R applyuser:applyuser /audio 2>/dev/null || true; fi

# Keep the container alive so `docker compose exec` can be used.
exec sleep infinity