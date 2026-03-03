# GitHub MCP Plugin for ATK

Work with repos, code, PRs, and issues from chat — powered by GitHub's official MCP server.

## Overview

This plugin connects AI agents directly to GitHub via the Model Context Protocol. Agents can search repositories,
read files, inspect commit history, file issues, open pull requests, and review changes — all from the conversation.

The upstream server is maintained by GitHub and distributed as `@github/mcp-server` on npm.

## Installation

Requires: Node.js / npx (comes with Node.js)

```bash
atk add github
```

ATK will prompt for your `GITHUB_TOKEN`. No separate install or start step is needed — this is an MCP-only plugin.

## Environment Variables

| Variable       | Default      | Description                                                                                     |
|----------------|--------------|-------------------------------------------------------------------------------------------------|
| `GITHUB_TOKEN` | —            | **Required.** Personal access token or GitHub App token with `repo`, `issues`, `pull_requests` scopes. |
| `GITHUB_HOST`  | `github.com` | GitHub host for GitHub Enterprise Server (e.g. `github.mycompany.com`). Leave default for github.com. |

### Creating a GitHub Token

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Click **Generate new token (classic)**
3. Select scopes: `repo`, `read:org` (for org repos), `read:user`
4. Copy the token and provide it during `atk add github`

## Usage

After setup, get the MCP configuration for your AI client:

```bash
atk mcp github
```

To reconfigure environment variables:

```bash
atk setup github
```

## MCP Tools

### Repository Operations

- **search_repositories** — Search GitHub repositories by query
- **get_repository** — Get repository metadata and details
- **list_branches** — List branches in a repository
- **list_commits** — List commits on a branch
- **get_file_contents** — Read file or directory contents at a path/ref
- **create_or_update_file** — Create or update a file in a repository

### Issues

- **list_issues** — List issues with filters (state, labels, assignee)
- **get_issue** — Get a specific issue by number
- **create_issue** — Create a new issue
- **update_issue** — Update issue title, body, state, labels, or assignees
- **add_issue_comment** — Add a comment to an issue
- **search_issues** — Search issues and PRs across GitHub

### Pull Requests

- **list_pull_requests** — List pull requests with filters
- **get_pull_request** — Get a specific PR by number
- **create_pull_request** — Open a new pull request
- **update_pull_request** — Update PR title, body, or state
- **get_pull_request_diff** — Get the diff for a pull request
- **merge_pull_request** — Merge a pull request

### Code Search

- **search_code** — Search code across GitHub repositories

## Links

- [GitHub MCP Server](https://github.com/github/github-mcp-server)
- [GitHub Token Settings](https://github.com/settings/tokens)
- [MCP Protocol](https://modelcontextprotocol.io)

