"""Cline-backed agent implementation.

This backend drives a local Cline installation (``npm i -g cline``) instead of
the built-in OpenRouter loop.  Cline is given the MusicBee tagger MCP tools
through its own MCP configuration and asked to process the requested playlist
job using the same path-free token workflow as the OpenRouter backend.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


CLINE_BIN_ENV = "CLINE_BIN"
DEFAULT_CLINE_COMMAND = "cline"


def find_cline(cline_bin: Optional[str] = None) -> Optional[str]:
    """Return the path to a usable Cline executable, if available."""
    candidate = cline_bin or os.environ.get(CLINE_BIN_ENV) or DEFAULT_CLINE_COMMAND
    if os.path.isabs(candidate) or os.sep in candidate or (os.altsep and os.altsep in candidate):
        if Path(candidate).is_file():
            return candidate
        return None
    return shutil.which(candidate)


def is_available(cline_bin: Optional[str] = None) -> bool:
    return find_cline(cline_bin) is not None


def build_task_prompt(job_id: Optional[str] = None) -> str:
    """Build the task prompt handed to Cline."""
    parts = [
        "You are a music metadata agent for the MusicBee Tagger MCP server.",
        "Use only the MCP tools exposed by the musicbee-tagger-mcp server; never "
        "request, repeat, or expose filesystem paths.",
        "Process audio files one at a time using their opaque tokens.",
        "For each token: search a canonical release, verify the MusicBrainz "
        "recording, then stage corrected tags. Mark unresolved tokens explicitly.",
        "Every staged file must include a non-empty genre.",
        "When every file in the batch is staged or marked unresolved, call "
        "finish_batch with a one-line summary.",
    ]
    if job_id:
        parts.append(f"Use playlist job id {job_id!r} for all batch operations.")
    else:
        parts.append(
            "If exactly one playlist job has pending tracks, select it "
            "automatically; otherwise ask for a job id."
        )
    return " ".join(parts)


def build_mcp_config(
    *,
    server_command: Optional[Sequence[str]] = None,
    data_dir: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Build a Cline-compatible MCP server configuration dictionary."""
    if server_command is None:
        server_command = [sys.executable, "-m", "musicbee_tagger_mcp.server"]
    if isinstance(server_command, str):
        server_command = server_command.split()
    server_command = list(server_command)
    if not server_command:
        server_command = [sys.executable, "-m", "musicbee_tagger_mcp.server"]
    server: dict[str, Any] = {
        "type": "stdio",
        "command": server_command[0],
    }
    if len(server_command) > 1:
        server["args"] = list(server_command[1:])
    merged_env = dict(env or {})
    if data_dir:
        merged_env["MUSICBEE_TAGGER_DATA_DIR"] = str(data_dir)
    if merged_env:
        server["env"] = merged_env
    return {"mcpServers": {"musicbee-tagger": server}}


def write_mcp_config(
    path: Optional[Path] = None,
    **kwargs: Any,
) -> Path:
    """Write an MCP configuration file and return its path."""
    if path is None:
        fd, name = tempfile.mkstemp(prefix="musicbee-cline-mcp-", suffix=".json")
        path = Path(name)
        os.close(fd)
    path = Path(path)
    path.write_text(
        json.dumps(build_mcp_config(**kwargs), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def build_cline_command(
    job_id: Optional[str] = None,
    *,
    cline_bin: Optional[str] = None,
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    auto_approve: bool = True,
    json_output: bool = True,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    system_prompt: Optional[str] = None,
    extra_args: Optional[Sequence[str]] = None,
) -> list[str]:
    """Construct the command line used to invoke Cline."""
    executable = find_cline(cline_bin)
    if executable is None:
        executable = cline_bin or os.environ.get(CLINE_BIN_ENV) or DEFAULT_CLINE_COMMAND
    command: list[str] = [executable]
    if json_output:
        command.append("--json")
    command.extend(["--auto-approve", "true" if auto_approve else "false"])
    if model:
        command.extend(["-m", str(model)])
    if provider:
        command.extend(["-P", str(provider)])
    if cwd:
        command.extend(["-c", str(cwd)])
    if timeout is not None:
        command.extend(["-t", str(timeout)])
    if system_prompt:
        command.extend(["-s", system_prompt])
    if extra_args:
        command.extend(list(extra_args))
    command.append(prompt if prompt is not None else build_task_prompt(job_id))
    return command


class ClineResult(int):
    def __new__(cls, returncode, process=None):
        obj=super().__new__(cls, int(returncode if returncode is not None else 0)); obj.returncode=int(returncode if returncode is not None else 0); obj.process=process; return obj


def run(
    job_id: Optional[str] = None,
    *,
    cline_bin: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    auto_approve: bool = True,
    json_output: bool = True,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    system_prompt: Optional[str] = None,
    prompt: Optional[str] = None,
    extra_args: Optional[Sequence[str]] = None,
    mcp_config: Optional[Any] = None,
    data_dir: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    check: bool = False,
    **_kwargs: Any,
) -> Any:
    """Run a Cline-backed tagging session.

    Returns the process return code when Cline is available.  When it is not
    available, prints an actionable message and returns ``127`` instead of
    raising, so callers can handle the missing dependency gracefully.
    """
    executable = find_cline(cline_bin)
    if executable is None:
        print(
            "Cline CLI not found. Install it with `npm i -g cline` and "
            "authenticate with `cline auth`.",
            file=sys.stderr,
        )
        return ClineResult(127)

    command_env = dict(os.environ)
    if env:
        command_env.update(env)

    config_path: Optional[Path] = None
    if mcp_config is None and os.environ.get("CLINE_MCP_SETTINGS_PATH") is None:
        try:
            config_path = write_mcp_config(data_dir=data_dir)
            command_env["CLINE_MCP_SETTINGS_PATH"] = str(config_path)
        except Exception:
            config_path = None
    elif isinstance(mcp_config, (str, Path)):
        command_env["CLINE_MCP_SETTINGS_PATH"] = str(mcp_config)
    elif isinstance(mcp_config, Mapping):
        try:
            config_path = write_mcp_config(**dict(mcp_config))
            command_env["CLINE_MCP_SETTINGS_PATH"] = str(config_path)
        except Exception:
            pass

    command = build_cline_command(
        job_id,
        cline_bin=executable,
        prompt=prompt,
        model=model,
        provider=provider,
        auto_approve=auto_approve,
        json_output=json_output,
        timeout=timeout,
        cwd=cwd,
        system_prompt=system_prompt,
        extra_args=extra_args,
    )

    completed = subprocess.run(
        command,
        cwd=cwd,
        env=command_env,
        check=check,
    )
    return ClineResult(getattr(completed, "returncode", 0), completed)


# Compatibility aliases used by callers and tests.
run_cline = run
cline_run = run
main = run


if __name__ == "__main__":
    raise SystemExit(run())
