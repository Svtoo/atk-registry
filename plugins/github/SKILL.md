# GitHub — Agent Skill

This MCP provides access to the GitHub API. Use it to work with repositories, issues, pull requests, and code —
searching, reading, creating, and modifying GitHub resources from chat.

## Tools

### Repositories
- **search_repositories**: Find repos by keyword, language, topic, or stars. Use before any repo work to confirm the correct full name.
- **get_file_contents**: Read a file or list a directory at a specific ref (branch, commit, tag). Use this to inspect source code.
- **list_commits**: List recent commits on a branch — useful for understanding recent changes.
- **create_branch**: Create a branch before making any file edits.
- **create_repository** / **fork_repository**: Create new repos or forks.

### Issues
- **list_issues** / **get_issue**: List or retrieve issues. Filter by state (`open`, `closed`), labels, or assignee.
- **create_issue**: File a new issue with title, body, labels, and assignees.
- **update_issue**: Modify title, body, state, labels, or assignees on an existing issue.
- **add_issue_comment**: Add a comment to an issue.
- **search_issues**: Cross-repo search — accepts GitHub search syntax (e.g., `is:open label:bug`).

### Pull Requests
- **list_pull_requests** / **get_pull_request**: List or retrieve PRs. Supports state and branch filters.
- **create_pull_request**: Open a PR from a head branch into a base branch.
- **get_pull_request_diff** / **list_pull_request_files**: Inspect what a PR changes before reviewing.
- **create_pull_request_review**: Submit APPROVE, REQUEST_CHANGES, or COMMENT reviews.
- **merge_pull_request**: Merge a PR (supports squash, merge, or rebase strategies).

### Files (Write Path)
- **create_or_update_file**: Create or update a single file in a repo. Requires the file's current SHA if updating.
- **push_files**: Push multiple files in one commit — more efficient than calling create_or_update_file repeatedly.

### Search & Identity
- **search_code**: Search code across all of GitHub. Accepts GitHub code search syntax.
- **search_users**: Find GitHub users by name or email.
- **get_me**: Get the authenticated user's login and profile — useful to confirm which account the token belongs to.

## Usage Patterns

**Making a code change via PR:**
1. `search_repositories` to confirm the repo name
2. `create_branch` off the target base branch
3. `get_file_contents` to read the file(s) to change + capture SHAs
4. `push_files` (or `create_or_update_file`) to write changes
5. `create_pull_request` to open the PR

**Reviewing an open PR:**
1. `list_pull_requests` to find the PR number
2. `get_pull_request_diff` to see what changed
3. `create_pull_request_review` to submit feedback

**Filing an issue:**
1. `search_issues` first to avoid duplicates
2. `create_issue` with a clear title and reproduction steps

## Notes

- All write operations (create_issue, create_pull_request, push_files, etc.) require a token with `repo` scope.
- For GitHub Enterprise, set `GITHUB_HOST` to the server hostname — all API calls route there automatically.
- `get_file_contents` returns base64-encoded content for binary files; text files are decoded automatically.
- When updating a file, you must supply the current file SHA (from a prior `get_file_contents` call) — missing it causes a 422 error.

