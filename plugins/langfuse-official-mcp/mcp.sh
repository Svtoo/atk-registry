#!/usr/bin/env bash
# Bridges the official Langfuse MCP server (Streamable HTTP at
# <LANGFUSE_HOST>/api/public/mcp) to stdio via mcp-remote, authenticating with
# HTTP Basic built from the Langfuse public + secret keys.
#
# CONFIG IS SELF-CONTAINED. All settings — including secrets — are read from this
# plugin's own .env at runtime. The agent's MCP config only needs to invoke this
# script; no keys are written into (or exposed through) the agent configuration.
# Editing .env (e.g. via `atk setup`) takes effect on the next restart with no
# re-plug, and the .env values win over anything the agent may have injected.
#
# Set LANGFUSE_MCP_DRYRUN=1 to print the resolved npx invocation (auth masked)
# and exit without connecting — used for local verification.
set -euo pipefail

# Load this plugin's .env (the single source of truth). `set -a` exports every
# assignment; values here override any stale env the agent snapshotted at plug
# time, so the bridge can't be pointed at the wrong host by a cached config.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/.env"
    set +a
fi

if [[ -z "${LANGFUSE_PUBLIC_KEY:-}" || -z "${LANGFUSE_SECRET_KEY:-}" || -z "${LANGFUSE_HOST:-}" ]]; then
    echo "ERROR: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HOST must be set in $SCRIPT_DIR/.env" >&2
    echo "Configure them with: atk setup langfuse-official-mcp" >&2
    exit 1
fi

HOST="${LANGFUSE_HOST%/}" # strip trailing slash so the endpoint is always well-formed

AUTH=$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 | tr -d '\n')
ENDPOINT="${HOST}/api/public/mcp"

# Langfuse speaks Streamable HTTP and authenticates via the static header above —
# it has no OAuth metadata. Pin the transport to http-only so an auth failure
# surfaces cleanly instead of falling back to a (broken) SSE handshake.
if [[ -n "${LANGFUSE_MCP_DRYRUN:-}" ]]; then
    echo "npx -y mcp-remote ${ENDPOINT} --transport http-only --header \"Authorization: Basic <redacted:${#AUTH}b>\""
    exit 0
fi

exec npx -y mcp-remote "${ENDPOINT}" --transport http-only --header "Authorization: Basic ${AUTH}"
