# git-local

Inspect and perform Git operations on local repositories via MCP — no remote auth required.

## Overview

This plugin wraps [`mcp-server-git`](https://github.com/modelcontextprotocol/servers/tree/main/src/git),
the official Git MCP server maintained by the Model Context Protocol organisation. It exposes Git
read and write operations to AI agents through the stdio transport, allowing agents to inspect
branches, commits, diffs, and working-tree status without any remote credentials.

MCP-only — no background service is required.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (provides `uvx`) must be installed and on `PATH`.
  Install with: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- The target directory must be a valid Git repository.

## Installation

```bash
atk add git-local
```

ATK will prompt for `GIT_REPO_PATH`. Set it to the absolute path of the repository you want
to work with (e.g. `/Users/you/projects/myrepo`). Leave it as `.` to use the working directory
of the MCP client at runtime.

## Environment Variables

| Variable        | Default | Description                                                                 |
|-----------------|---------|-----------------------------------------------------------------------------|
| `GIT_REPO_PATH` | `.`     | Path to the Git repository to operate on (absolute or relative to client cwd) |

## Usage

After adding the plugin, get the MCP configuration for your client:

```bash
atk mcp show git-local
```

To reconfigure the repository path:

```bash
atk setup git-local
```

## MCP Tools

| Tool                | Description                                            |
|---------------------|--------------------------------------------------------|
| `git_status`        | Show working-tree status (staged, unstaged, untracked) |
| `git_diff_unstaged` | Show unstaged changes                                  |
| `git_diff_staged`   | Show staged (indexed) changes                          |
| `git_diff`          | Show diff between two branches or commits              |
| `git_log`           | Show commit history with optional branch filter        |
| `git_show`          | Show contents of a specific commit                     |
| `git_branch`        | List local branches                                    |
| `git_checkout`      | Switch to an existing branch                           |
| `git_create_branch` | Create a new branch (optionally from a base ref)       |
| `git_add`           | Stage files for commit                                 |
| `git_reset`         | Unstage files                                          |
| `git_commit`        | Create a commit with a message                         |

## Links

- [Upstream repository](https://github.com/modelcontextprotocol/servers/tree/main/src/git)
- [mcp-server-git on PyPI](https://pypi.org/project/mcp-server-git/)
- [Model Context Protocol](https://modelcontextprotocol.io)

