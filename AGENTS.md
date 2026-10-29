# Repository agent guidance

## Tool use before shell commands

- Do not run shell commands (bash, cmd, powershell, python, etc.) without first making absolutely sure that the required action cannot be performed using an existing exposed tool (MCP tool, skill, or other available tool). Prefer the exposed tool; use a shell only as a last resort and state why no exposed tool can do it.


## Validation and pushing changes

- Always run tests relevant to code changes before finishing work, using the project's virtual environment when available.
- Push completed changes to the current working branch on `origin`; do not push work directly to `main` or `master`.
- Treat filename-derived artist/title candidates as unverified research clues; corroborate them independently before proposing tag values.

## Branches for issue work

- Always create and switch to a new branch before making changes to address a new issue.
- Name the branch with the an appropriate agent specific prefix such as 'claude/' or 'codex/' and include the issue number and a short description when available (for example, `codex/issue-30-multigenre`).
- Keep the issue changes and any related tests or documentation on that branch.
- When working in a temporary or virtual computer, push issue work to `origin` and keep the working directory synchronized with the remote so changes survive environment loss.
