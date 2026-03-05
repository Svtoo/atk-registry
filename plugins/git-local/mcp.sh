#!/bin/bash
# git-local MCP wrapper
# Launches mcp-server-git pointed at the configured repository path.
# GIT_REPO_PATH is injected by ATK from the plugin's .env file.

exec uvx mcp-server-git --repository "${GIT_REPO_PATH:-.}"

