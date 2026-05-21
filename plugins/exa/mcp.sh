#!/usr/bin/env bash
# Bridges Exa's remote Streamable-HTTP MCP via mcp-remote over stdio,
# and passes EXA_API_KEY as an x-api-key header if set.
set -euo pipefail

[[ "${EXA_API_KEY:-}" == "<NOT_SET>" ]] && unset EXA_API_KEY

ARGS=("-y" "mcp-remote" "https://mcp.exa.ai/mcp")

if [[ -n "${EXA_API_KEY:-}" ]]; then
    ARGS+=("--header" "x-api-key: $EXA_API_KEY")
fi

exec npx "${ARGS[@]}"
