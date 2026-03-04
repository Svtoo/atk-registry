#!/bin/bash
# GitLab MCP server launcher.
# Connects to the GitLab Duo MCP server via mcp-remote (stdio transport).
# Auth is handled via OAuth 2.0 browser flow on first connect.
# Requires: Node.js 20+ with npx available.

# Strip any trailing slash from GITLAB_URL before building the endpoint URL.
# This prevents double-slash (e.g. https://example.com//api/v4/mcp) when the
# user supplies a URL with a trailing slash.
BASE_URL="${GITLAB_URL:-https://gitlab.com}"
BASE_URL="${BASE_URL%/}"
ENDPOINT="${BASE_URL}/api/v4/mcp"
exec npx -y mcp-remote "$ENDPOINT"

