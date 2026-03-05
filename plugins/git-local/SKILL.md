# git-local — Agent Skill

Provides read and write Git operations on a local repository configured by the user. Use this
MCP to inspect history, branches, diffs, and working-tree state without requiring any remote
credentials.

## Tools

- **git_status**: Shows staged, unstaged, and untracked files. Use before committing or to check
  for unexpected changes.
- **git_diff_unstaged**: Shows changes not yet staged. Use to review work-in-progress edits.
- **git_diff_staged**: Shows changes staged for the next commit. Use to review what will be
  committed.
- **git_diff**: Shows diff between two refs (branch names or commit SHAs). Useful for comparing
  feature branches.
- **git_log**: Shows commit history. Accepts branch name and max count. Use to understand recent
  changes.
- **git_show**: Shows the contents of a specific commit. Use to inspect what a particular SHA
  introduced.
- **git_branch**: Lists local branches. Use to discover available branches before checking out.
- **git_checkout**: Switches to an existing branch. Does NOT create new branches. Prefer this
  over creating new branches unless explicitly asked.
- **git_create_branch**: Creates a new branch, optionally from a base ref. Use only when the
  user explicitly requests a new branch.
- **git_add**: Stages files for commit. Use only when the user explicitly wants to stage changes.
- **git_reset**: Unstages files. Use to undo a git_add.
- **git_commit**: Creates a commit with a message. Use only when the user explicitly authorises
  a commit.

## Usage Patterns

**Safe inspection workflow** (no side effects):
1. `git_status` → understand current state
2. `git_log` → review recent commits
3. `git_diff_unstaged` / `git_diff_staged` → inspect changes

**Branch comparison**:
1. `git_branch` → list available branches
2. `git_diff` with two branch names → see divergence

## Notes

- `git_checkout`, `git_add`, `git_commit`, and `git_create_branch` **modify the working tree or
  history**. Only call these when the user explicitly requests the action.
- The repository operated on is fixed by `GIT_REPO_PATH` in the plugin config. To switch repos,
  reconfigure via `atk setup git-local`.
- Read-only tools (`git_status`, `git_log`, `git_diff*`, `git_show`, `git_branch`) are always
  safe to call freely.

