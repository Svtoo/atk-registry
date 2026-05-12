#!/usr/bin/env bash
# Serena MCP launch wrapper.
#
# ATK substitutes only $ATK_PLUGIN_DIR in plugin.yaml mcp.args — user-tunable
# CLI flags have to be assembled from env vars here at runtime. ATK injects
# every var listed in mcp.env into our environment before exec'ing this script,
# so $SERENA_CONTEXT lands here populated from .env (or the plugin.yaml default).

set -euo pipefail

# Defensive: ATK's display layer uses a "<NOT_SET>" sentinel for missing-but-
# required vars. It shouldn't reach optional vars with defaults, but guard
# anyway — a misconfigured environment is better than a silently broken server.
CONTEXT="${SERENA_CONTEXT:-ide}"
[[ "$CONTEXT" == "<NOT_SET>" || -z "$CONTEXT" ]] && CONTEXT="ide"

exec serena start-mcp-server \
    --context "$CONTEXT" \
    --project-from-cwd
