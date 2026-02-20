#!/usr/bin/env bash
# Playwright MCP wrapper script.
#
# @playwright/mcp uses presence-only boolean flags (--headless, --ignore-https-errors).
# They do NOT accept =true / =false.  Passing --headless=false causes
# "unknown option" and immediately closes the connection (MCP -32000).
#
# This script conditionally includes boolean flags and correctly resolves
# the PLAYWRIGHT_OUTPUT_DIR when it still holds the unexpanded $ATK_PLUGIN_DIR
# placeholder written by `atk setup`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Normalize ATK's <NOT_SET> placeholder so bash defaults work for users
# who haven't configured the plugin via `atk setup playwright`.
for _var in PLAYWRIGHT_BROWSER PLAYWRIGHT_HEADLESS PLAYWRIGHT_VIEWPORT \
            PLAYWRIGHT_TIMEOUT_ACTION PLAYWRIGHT_TIMEOUT_NAVIGATION \
            PLAYWRIGHT_IGNORE_HTTPS_ERRORS PLAYWRIGHT_OUTPUT_DIR; do
    [[ "${!_var:-}" == "<NOT_SET>" ]] && unset "$_var"
done
unset _var

ARGS=("-y" "@playwright/mcp@latest")

# Browser
ARGS+=("--browser" "${PLAYWRIGHT_BROWSER:-chromium}")

# --headless: presence-only boolean flag
if [ "${PLAYWRIGHT_HEADLESS:-false}" = "true" ]; then
    ARGS+=("--headless")
fi

# Viewport and timeouts
ARGS+=("--viewport-size"      "${PLAYWRIGHT_VIEWPORT:-1280x720}")
ARGS+=("--timeout-action"     "${PLAYWRIGHT_TIMEOUT_ACTION:-5000}")
ARGS+=("--timeout-navigation" "${PLAYWRIGHT_TIMEOUT_NAVIGATION:-60000}")

# --ignore-https-errors: presence-only boolean flag
if [ "${PLAYWRIGHT_IGNORE_HTTPS_ERRORS:-false}" = "true" ]; then
    ARGS+=("--ignore-https-errors")
fi

# Output dir — fall back to the plugin directory when the env var still holds
# the unexpanded "$ATK_PLUGIN_DIR/output" placeholder from `atk setup`.
OUTPUT_DIR="${PLAYWRIGHT_OUTPUT_DIR:-}"
if [ -z "$OUTPUT_DIR" ] || [[ "$OUTPUT_DIR" == *'$ATK_PLUGIN_DIR'* ]]; then
    OUTPUT_DIR="$SCRIPT_DIR/output"
fi
ARGS+=("--output-dir" "$OUTPUT_DIR")

exec npx "${ARGS[@]}"

