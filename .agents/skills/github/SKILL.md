---
name: github
description: >-
  Helper skill for GitHub CLI operations using run_commands. Use this when posting
  comments, viewing issues, creating pull requests, or listing issues/PRs.
---

# GitHub CLI Helper

Use `run_commands` to invoke the GitHub CLI (`gh`). Never assume a dedicated
`gh_issue_comment` tool exists unless it is listed; `run_commands` is always
available.

## Common operations

- Post a comment:
  `gh issue comment <number> --body "..."`
- View issue details/comments:
  `gh issue view <number> --json comments`
- Create a pull request:
  `gh pr create --title "..." --body "..."`
- List pull requests:
  `gh pr list`
- List issues:
  `gh issue list`

Always pass commands as an array of strings to `run_commands`, e.g.
`run_commands([

ssue view <number> --json comments`
- Create a pull request:
  `gh pr create --title "..." --body "..."`
- List pull requests:
  `gh pr list`
- List issues:
  `gh issue list`

Always pass commands as an array of non-empty strings to `run_commands`.
EOF