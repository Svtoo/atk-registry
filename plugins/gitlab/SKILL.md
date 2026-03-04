# GitLab — Skill

This MCP provides access to GitLab via the official GitLab Duo MCP server (Beta). Use it to search and read
project content, manage issues and merge requests, and browse source files — all without leaving the
conversation.

## Authentication

Authentication is via OAuth 2.0 browser flow. On first connection, the MCP client opens a browser window for
GitLab authorization. No personal access token is required.

## Capabilities

The GitLab MCP server exposes tools in these areas (exact tool names are managed by GitLab):

- **Projects**: browse, search, and read project metadata
- **Issues**: list, create, and update issues
- **Merge requests**: list, create, and inspect merge requests
- **Repository files**: read file contents and directory listings

## Usage Patterns

- Discover project IDs before operating on issues or MRs.
- Combine repository browsing tools to navigate the file tree (list directory, then read file).
- When creating MRs to close issues, include `Closes #<issue-id>` in the description.

## Notes

- Requires GitLab Duo enabled (Premium or Ultimate tier) with beta features turned on.
- `GITLAB_URL` defaults to `https://gitlab.com`; set it to your instance URL for self-hosted GitLab.
- The tool list is server-side and may change between GitLab versions. Use tool discovery to inspect available tools.
- See: https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server/

