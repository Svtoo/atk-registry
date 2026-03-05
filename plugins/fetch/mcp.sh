#!/usr/bin/env bash
# mcp-server-fetch wrapper.
#
# USER_AGENT is passed as --user-agent=VALUE to uvx — the server reads it
# from its CLI args, not from os.environ.  This script conditionally appends
# the flag so users who leave USER_AGENT unset get the default MCP user-agent.

set -euo pipefail

# Normalise ATK's <NOT_SET> placeholder so bash defaults apply correctly
# for optional env vars that were skipped during `atk add / atk setup`.
[[ "${USER_AGENT:-}" == "<NOT_SET>" ]] && unset USER_AGENT

ARGS=("mcp-server-fetch")

if [ -n "${USER_AGENT:-}" ]; then
    ARGS+=("--user-agent=$USER_AGENT")
fi

exec uvx "${ARGS[@]}"

