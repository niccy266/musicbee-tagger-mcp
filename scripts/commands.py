from __future__ import annotations

import shlex
import subprocess
from typing import Any, Dict, Optional, Union


CommandResult = Union[str, Dict[str, Any], list]


def _type_name(value: Any) -> str:
    return type(value).__name__


def validate_commands(commands: Any) -> Optional[str]:
    if not isinstance(commands, (list, tuple)):
        return "Expected array of strings, got {}".format(_type_name(commands))
    if len(commands) == 0:
        return "Expected non-empty array of strings, got empty array"
    for index, command in enumerate(commands):
        if not isinstance(command, str):
            return (
                "Expected string (non-empty) command at index {}, got {}".format(
                    index, _type_name(command)
                )
            )
        if not command.strip():
            return (
                "Expected non-empty string command at index {}, got empty string".format(
                    index
                )
            )
    return None


validate_run_commands = validate_commands
validate_run_commands_input = validate_commands
check_commands = validate_commands


def _run_subprocess(command: str) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
        )
    except Exception as error:
        return {
            "command": command,
            "stdout": "",
            "stderr": str(error),
            "returncode": 1,
            "error": str(error),
        }
    result = {
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
    if completed.returncode != 0:
        result["error"] = (
            completed.stderr.strip()
            or "command exited with status {}".format(completed.returncode)
        )
    return result


def run_commands(commands: Any) -> Any:
    error = validate_commands(commands)
    if error is not None:
        result = {"error": error}
        try:
            from musicbee_tagger_mcp.error_codes import E_INVALID_INPUT, make_error

            result = make_error(E_INVALID_INPUT, error, function="run_commands")
        except Exception:
            pass
        return result

    results = [_run_subprocess(command) for command in commands]
    return {"results": results, "commands": list(commands)}


run_command = run_commands
execute_commands = run_commands
execute_command = run_commands
commands = run_commands


def gh_issue_comment(
    issue: Any = None,
    body: str = "",
    repo: Optional[str] = None,
    number: Any = None,
    issue_number: Any = None,
    comment_body: Optional[str] = None,
) -> Any:
    resolved_issue = issue
    if resolved_issue is None:
        resolved_issue = issue_number if issue_number is not None else number
    resolved_body = body
    if resolved_body in (None, ""):
        resolved_body = comment_body if comment_body is not None else ""

    if resolved_issue is None:
        return {
            "error": "issue number is required",
            "error_code": "E_INVALID_INPUT",
            "function": "gh_issue_comment",
        }
    if not str(resolved_body).strip():
        return {
            "error": "comment body is required",
            "error_code": "E_INVALID_INPUT",
            "function": "gh_issue_comment",
        }

    parts = ["gh", "issue", "comment", str(resolved_issue)]
    if repo:
        parts.extend(["--repo", str(repo)])
    parts.extend(["--body", shlex.quote(str(resolved_body))])
    command = " ".join(parts)
    result = run_commands([command])
    if isinstance(result, dict):
        result.setdefault("tool", "gh_issue_comment")
    return result


github_issue_comment = gh_issue_comment
post_issue_comment = gh_issue_comment
comment_on_issue = gh_issue_comment
create_issue_comment = gh_issue_comment


def run_commands_validated(commands: Any) -> Any:
    error = validate_commands(commands)
    if error is not None:
        raise ValueError(error)
    return run_commands(commands)


__all__ = [
    "validate_commands",
    "validate_run_commands",
    "validate_run_commands_input",
    "check_commands",
    "run_commands",
    "run_command",
    "execute_commands",
    "execute_command",
    "commands",
    "run_commands_validated",
    "gh_issue_comment",
    "github_issue_comment",
    "post_issue_comment",
    "comment_on_issue",
    "create_issue_comment",
]
