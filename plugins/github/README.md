# GitHub MCP Plugin for ATK

GitHub integration via MCP — search repositories, read code, file issues, open pull requests, and review changes from chat.

## Overview

This plugin wraps [GitHub's official MCP server](https://github.com/github/github-mcp-server) to give AI agents
full access to the GitHub API through the Model Context Protocol. It supports both github.com and GitHub Enterprise
Server instances.

## Installation

Requires: [Docker](https://docs.docker.com/get-docker/) (installed and running)

```bash
atk add github
```

You will be prompted for your `GITHUB_PERSONAL_ACCESS_TOKEN`. For GitHub Enterprise, also set `GITHUB_HOST`.

## Environment Variables

| Variable                       | Default        | Description                                                                                              |
|--------------------------------|----------------|----------------------------------------------------------------------------------------------------------|
| `GITHUB_PERSONAL_ACCESS_TOKEN` | —              | **Required.** Personal access token or GitHub App token with `repo`, `issues`, and `pull_requests` scopes. |
| `GITHUB_HOST`                  | —              | Optional. GitHub Enterprise Server base URL **including scheme** (e.g. `https://github.mycompany.com`). Leave unset for public github.com. |

> **GitHub Enterprise users:** Set `GITHUB_HOST` to the full URL including `https://` when prompted
> during `atk add github`. Leave it empty (press Enter) to use public github.com.

### Generating a token

1. Go to **Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Create a token with scopes: `repo`, `read:org`, `read:user`
3. Set it as `GITHUB_PERSONAL_ACCESS_TOKEN`

## Usage

`atk add github` pulls the Docker image automatically. To update to the latest image:

```bash
atk install github
```

Get the MCP configuration for your client:

```bash
atk mcp show github
atk mcp show github --json
```

## MCP Tools

### Repositories

- `search_repositories` — Search GitHub repositories by keyword
- `get_file_contents` — Read file or directory contents from a repo
- `list_commits` — List commits for a branch
- `create_repository` — Create a new repository
- `fork_repository` — Fork a repository
- `create_branch` — Create a new branch

### Issues

- `list_issues` — List issues in a repository
- `get_issue` — Get a specific issue by number
- `create_issue` — Create a new issue
- `update_issue` — Update issue title, body, or labels
- `add_issue_comment` — Add a comment to an issue
- `search_issues` — Search issues and PRs by query

### Pull Requests

- `list_pull_requests` — List pull requests
- `get_pull_request` — Get a specific PR by number
- `create_pull_request` — Open a new pull request
- `update_pull_request` — Update PR title, body, or base branch
- `merge_pull_request` — Merge a pull request
- `get_pull_request_diff` — Get the diff for a PR
- `list_pull_request_files` — List files changed in a PR
- `create_pull_request_review` — Submit a review on a PR

### Files

- `create_or_update_file` — Create or update a file in a repository
- `push_files` — Push multiple files in a single commit

### Users & Search

- `get_me` — Get the authenticated user's profile
- `search_code` — Search code across GitHub
- `search_users` — Search GitHub users

## Links

- [GitHub MCP Server](https://github.com/github/github-mcp-server)
- [GitHub REST API Documentation](https://docs.github.com/en/rest)
- [Creating a personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

