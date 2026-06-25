#!/usr/bin/env bash
# Bridges Obsidian's "Local REST API with MCP" server (Streamable HTTP at
# <OBSIDIAN_HOST>/mcp/) to stdio via mcp-remote, authenticating with a static
# Bearer token.
#
# CONFIG IS SELF-CONTAINED. All settings — including the secret API key — are
# read from this plugin's own .env at runtime. The agent's MCP config only needs
# to invoke this script; no key is written into (or exposed through) the agent
# configuration. Editing .env (e.g. via `atk setup`) takes effect on the next
# restart with no re-plug, and the .env values win over anything the agent may
# have snapshotted at plug time.
#
# TLS: the Obsidian plugin serves HTTPS with a SELF-SIGNED certificate on
# localhost. Node rejects that by default, so unless OBSIDIAN_VERIFY_TLS=true
# (or the user supplied their own NODE_EXTRA_CA_CERTS bundle) we disable Node's
# TLS verification for THIS process only. The connection is to loopback
# (127.0.0.1), so there is no meaningful man-in-the-middle exposure.
#
# Set OBSIDIAN_MCP_DRYRUN=1 to print the resolved npx invocation (token masked)
# and exit without connecting — used for local verification.
set -euo pipefail

# Load this plugin's .env (the single source of truth). `set -a` exports every
# assignment so the values reach the npx subprocess; they also override any
# stale env the agent snapshotted at plug time.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/.env"
    set +a
fi

# ATK stores unset optional vars as the literal sentinel <NOT_SET>; treat as empty.
[[ "${OBSIDIAN_API_KEY:-}" == "<NOT_SET>" ]] && OBSIDIAN_API_KEY=""
[[ "${OBSIDIAN_HOST:-}" == "<NOT_SET>" ]] && OBSIDIAN_HOST=""
[[ "${OBSIDIAN_VERIFY_TLS:-}" == "<NOT_SET>" ]] && OBSIDIAN_VERIFY_TLS=""

# Normalize the API key. Obsidian's settings screen displays the key inside a
# "Bearer <key>" box, so it's natural to copy the whole line. Accept either form:
# trim surrounding whitespace and strip an optional, case-insensitive leading
# "Bearer " so the header is never doubled ("Authorization: Bearer Bearer ...").
_trim() { local s="$1"; s="${s#"${s%%[![:space:]]*}"}"; s="${s%"${s##*[![:space:]]}"}"; printf '%s' "$s"; }
OBSIDIAN_API_KEY="$(_trim "${OBSIDIAN_API_KEY:-}")"
if [[ "$OBSIDIAN_API_KEY" =~ ^[Bb][Ee][Aa][Rr][Ee][Rr][[:space:]]+(.+)$ ]]; then
    OBSIDIAN_API_KEY="$(_trim "${BASH_REMATCH[1]}")"
fi

if [[ -z "${OBSIDIAN_API_KEY:-}" ]]; then
    echo "ERROR: OBSIDIAN_API_KEY must be set in $SCRIPT_DIR/.env" >&2
    echo "Get it from Obsidian → Settings → Local REST API → 'Your API Key'," >&2
    echo "then run: atk setup obsidian-local-rest-api" >&2
    exit 1
fi

HOST="${OBSIDIAN_HOST:-https://127.0.0.1:27124}"
HOST="${HOST%/}" # strip trailing slash so the endpoint is always well-formed
VERIFY_TLS="${OBSIDIAN_VERIFY_TLS:-false}"
ENDPOINT="${HOST}/mcp/"

# Accept the plugin's self-signed cert on loopback unless the user opted into
# verification or pointed Node at their own CA bundle.
if [[ "$VERIFY_TLS" != "true" && -z "${NODE_EXTRA_CA_CERTS:-}" ]]; then
    export NODE_TLS_REJECT_UNAUTHORIZED=0
fi

# Obsidian's MCP endpoint speaks Streamable HTTP and authenticates via the static
# Bearer header below — it has no OAuth metadata. Pin the transport to http-only
# so an auth failure surfaces cleanly instead of falling back to an SSE handshake.
ARGS=("-y" "mcp-remote" "$ENDPOINT" "--transport" "http-only")
# mcp-remote refuses plain-HTTP URLs unless explicitly allowed.
[[ "$HOST" == http://* ]] && ARGS+=("--allow-http")
ARGS+=("--header" "Authorization: Bearer ${OBSIDIAN_API_KEY}")

if [[ -n "${OBSIDIAN_MCP_DRYRUN:-}" ]]; then
    echo "NODE_TLS_REJECT_UNAUTHORIZED=${NODE_TLS_REJECT_UNAUTHORIZED:-<unset>} npx -y mcp-remote ${ENDPOINT} --transport http-only$([[ "$HOST" == http://* ]] && echo ' --allow-http') --header \"Authorization: Bearer <redacted:${#OBSIDIAN_API_KEY}b>\""
    exit 0
fi

exec npx "${ARGS[@]}"
