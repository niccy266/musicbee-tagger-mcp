# CLAUDE Rules — Behavior Constraints (Session-Specific)

These rules override general coding-agent defaults for the duration of this session. Follow them with loyal strictness.

## 1. Command Execution — Extreme Selectivity

- Bash/shell/run_commands commands are a **LAST RESORT**. Use them only when no read/edit/write/web tool can accomplish the task.
- **Never** run commands that target items **outside the working directory** (`k:\dev\vibe-coding\musicbee-mcp-server`) unless explicitly required and unavoidable. When a command must reference an outside path, evaluate the risk critically first.
- Prefer absolute paths confined to the workspace. Do not write temp/helper scripts outside the workspace.
- If a command fails, do not blindly retry with variations. Reassess whether a read/edit/write tool could do the job instead.
- **Any tool that requires temp directories, scratch space, or generates logs must run inside the local working directory** (`k:\dev\vibe-coding\musicbee-mcp-server`). Do not write temp files, logs, or scratch artifacts to `C:\Users\...`, `AppData\Local\Temp`, or any location outside the workspace. This keeps all generated items accessible via the normal read/edit tools and forbids roaming outside the workspace.

## 2. Tool Preference Hierarchy

Prefer tools in this order:

1. **`read_files`** — inspect file contents.
2. **`search_codebase`** — locate patterns, definitions, imports.
3. **`editor`** (create/insert/replace) — make file edits; do not use shell redirection or `echo`/`> ` to create/modify files.
4. **`fetch_web_content` / `web_search`** — external documentation/API info.
5. **`run_commands`** — only when the above cannot do the task (e.g., running the project's test suite, git operations that cannot be done via available tools).

When editing a file, always attempt `editor` first. Only fall back to `run_commands` if `editor` cannot express the change.

## 3. Syntax & Correctness Discipline

- Before declaring an edit complete, validate it with an in-workspace check (e.g., `ast.parse` for Python) rather than assuming correctness.
- Take the time to get tool-call syntax correct on the first attempt; iterate using read tools to confirm file state rather than guessing.
- Do not omit code or leave placeholders. Provide complete, functional code.

## 4. Self-Evaluation (No Evaluator Present)

- This session has **no automated evaluator**. You are solely responsible for judging the correctness, safety, and completeness of your actions.
- Before each significant action, pause and consider: Is there a safer, in-workspace, tool-based way to do this? Am I modifying anything outside the workspace unintentionally? Have I validated the change?
- After completing a task, verify the final state of all edited files and run relevant tests.

## 5. Project-Specific Conventions (from AGENTS.md)

- **Do not run `pytest` locally in this environment.** Test validation is delegated to GitHub (CI / remote execution). Local `pytest` runs hit environment `PermissionError`s on the temp directory and are not representative of the real test outcome.
- Run relevant tests using the project's virtual environment (`.venv`) before finishing work.
- Push completed changes to the current working branch on `origin`; never push directly to `main` or `master`.
- Create a new branch (prefix `claude/` or `codex/`, include issue number + short description) before making changes for a new issue.
- Treat filename-derived artist/title candidates as unverified research clues; corroborate independently before proposing tag values.

## 6. Working Directory

- Root: `k:\dev\vibe-coding\musicbee-mcp-server`
- All file paths in tool calls must be absolute and within this root unless an exception is justified and documented.
