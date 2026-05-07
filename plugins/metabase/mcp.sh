#!/usr/bin/env bash
# Metabase MCP wrapper.
#
# Selects the upstream tool-set flag based on METABASE_TOOL_SET:
#   (unset|essential) → no flag — default 21-tool essentials set
#   all               → --all   — full 80+ tool surface (includes write/edit)
#   read              → --read  — read-only subset
#   write             → --write — write-only subset (rare)
#
# ATK only substitutes $ATK_PLUGIN_DIR in mcp.args, so user-tunable CLI flags
# must be assembled here at runtime (see ATK pattern note in plugin.yaml).

set -euo pipefail

# Normalize ATK's <NOT_SET> placeholder so the bash default below kicks in.
[[ "${METABASE_TOOL_SET:-}" == "<NOT_SET>" ]] && unset METABASE_TOOL_SET

ARGS=("-y" "@cognitionai/metabase-mcp-server")

case "${METABASE_TOOL_SET:-essential}" in
    essential|"") ;;                 # no flag — default essentials
    all)   ARGS+=("--all") ;;
    read)  ARGS+=("--read") ;;
    write) ARGS+=("--write") ;;
    *)
        echo "metabase mcp.sh: invalid METABASE_TOOL_SET='$METABASE_TOOL_SET'" \
             "(expected: essential, all, read, write)" >&2
        exit 64
        ;;
esac

exec npx "${ARGS[@]}"
