# GitHub — Agent Skill

This MCP provides direct access to GitHub's API for repository operations, issue tracking, and pull request management.
Use it to read code, file bugs, review changes, and open PRs without leaving the conversation.

## Tools

### Repositories
- **search_repositories**: Search GitHub for repositories by keyword, language, or org
- **get_repository**: Retrieve repo metadata (description, stars, default branch, topics)
- **list_branches**: List branches with their latest commit SHAs
- **list_commits**: View commit history on a branch, with author and message
- **get_file_contents**: Read a file or list a directory at any ref (branch, tag, or SHA)
- **create_or_update_file**: Write a file to a repository (requires write permission)

### Issues
- **list_issues**: List issues filtered by state, labels, or assignee
- **get_issue**: Read a specific issue including body, labels, and comments
- **create_issue**: File a new issue with title, body, labels, and assignees
- **update_issue**: Change issue title, body, state (open/closed), or labels
- **add_issue_comment**: Post a comment on an issue
- **search_issues**: Full-text search across issues and PRs on GitHub

### Pull Requests
- **list_pull_requests**: List PRs filtered by state, base branch, or author
- **get_pull_request**: Read a PR including description, reviewers, and status checks
- **create_pull_request**: Open a PR from a branch with title, body, and base
- **update_pull_request**: Edit PR title, body, or state
- **get_pull_request_diff**: Retrieve the unified diff for a PR
- **merge_pull_request**: Merge a PR (use with care — this is permanent)

### Code Search
- **search_code**: Search code across all of GitHub by keyword and language

## Usage Patterns

**Reading code in a PR:**
1. `get_pull_request` to understand the PR description and base/head branches
2. `get_pull_request_diff` to read the actual changes
3. `get_file_contents` for additional context from unchanged files

**Filing an issue from a conversation:**
1. Use `search_issues` first to avoid duplicates
2. `create_issue` with a clear title and body summarizing the problem

**Making a small fix:**
1. `get_file_contents` to read the current file
2. `create_or_update_file` to write the change (requires a commit message and branch)
3. `create_pull_request` to open a PR for review

## Notes

- `GITHUB_TOKEN` must have `repo` scope for private repositories; public repos work with `public_repo`.
- `create_or_update_file` requires the current file's blob SHA when updating an existing file — read it first with `get_file_contents`.
- For GitHub Enterprise Server, `GITHUB_HOST` must be set to the instance hostname (not the full URL).
- Write operations (create_issue, create_pull_request, merge_pull_request) are permanent — confirm intent before calling.
- Rate limits apply: authenticated requests get 5,000 req/hour; search API is 30 req/minute.

