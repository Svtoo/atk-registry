#!/usr/bin/env bash
# Serena MCP launch wrapper.
#
# ATK substitutes only $ATK_PLUGIN_DIR in plugin.yaml mcp.args — user-tunable
# CLI flags have to be assembled from env vars here at runtime. ATK injects
# every var listed in mcp.env into our environment before exec'ing this script,
# so $SERENA_CONTEXT and $SERENA_DASHBOARD land here populated from .env (or
# the plugin.yaml defaults).

set -euo pipefail

# Defensive: ATK's display layer uses a "<NOT_SET>" sentinel for missing-but-
# required vars. It shouldn't reach optional vars with defaults, but guard
# anyway — a misconfigured environment is better than a silently broken server.
CONTEXT="${SERENA_CONTEXT:-ide}"
[[ "$CONTEXT" == "<NOT_SET>" || -z "$CONTEXT" ]] && CONTEXT="ide"

DASHBOARD="${SERENA_DASHBOARD:-off}"
[[ "$DASHBOARD" == "<NOT_SET>" || -z "$DASHBOARD" ]] && DASHBOARD="off"

# Translate the SERENA_DASHBOARD tri-state to Serena's two boolean flags.
# Default (off) avoids the auto-opening browser tab Serena ships with.
DASHBOARD_ARGS=()
case "$DASHBOARD" in
    off)
        DASHBOARD_ARGS+=("--enable-web-dashboard" "false")
        ;;
    headless)
        DASHBOARD_ARGS+=("--enable-web-dashboard" "true" "--open-web-dashboard" "false")
        ;;
    open)
        DASHBOARD_ARGS+=("--enable-web-dashboard" "true" "--open-web-dashboard" "true")
        ;;
    *)
        echo "serena mcp.sh: invalid SERENA_DASHBOARD='$DASHBOARD'" \
             "(expected: off, headless, open)" >&2
        exit 64
        ;;
esac

exec serena start-mcp-server \
    --context "$CONTEXT" \
    --project-from-cwd \
    "${DASHBOARD_ARGS[@]}"
