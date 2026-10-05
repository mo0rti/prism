"""Run one agent host once: build its command, run it with the token in its environment, keep sanitized records.

Claude Code is the npm package's ``claude.exe`` with the prompt on stdin (the
``claude.cmd`` shim cuts multi-line prompts). Codex is ``codex exec`` with the
prompt on stdin. Each host reaches the board through an MCP configuration that
reads the token from ``PRISM_BOARD_TOKEN``; the user's own Claude Code and Codex
configuration is not changed (Codex's ``-c`` overrides apply to this run only,
and Claude Code's ``--strict-mcp-config`` ignores every other MCP server).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Sequence

from .config import HostModel
from .procs import ProcessResult, clean_env, run_captured
from .tokens import TokenRegistry
from .transcripts import (
    HostTranscript,
    claude_session_efforts,
    claude_session_models,
    codex_rollout_model_effort,
    parse_claude_stream,
    parse_codex_stream,
)


@dataclass
class HostRun:
    host: str
    run_kind: str  # "preview" or "apply"
    command_shown: str
    result: ProcessResult
    transcript: HostTranscript
    recorded_models: set[str]
    recorded_efforts: set[str]

    @property
    def exit_ok(self) -> bool:
        return not self.result.timed_out and self.result.exit_code == 0


def claude_mcp_config(port: int) -> dict:
    """The MCP configuration shape from docs/shared-board.md. The token stays a variable reference."""

    return {
        "mcpServers": {
            "prism": {
                "type": "http",
                "url": f"http://127.0.0.1:{port}/mcp",
                "headers": {"Authorization": "Bearer ${PRISM_BOARD_TOKEN}"},
            }
        }
    }


def claude_command(executable: Path, model: HostModel, mcp_config: Path) -> list[str]:
    command = [str(executable), "-p", "--model", model.model]
    if model.effort:
        command += ["--effort", model.effort]
    command += [
        "--output-format", "stream-json", "--verbose",
        "--mcp-config", str(mcp_config), "--strict-mcp-config",
        "--tools", "",
        "--allowedTools", "mcp__prism__*",
    ]
    return command


def codex_command(executable: Path, model: HostModel, workspace: Path, last_message: Path, port: int) -> list[str]:
    command = [str(executable), "exec", "-m", model.model]
    if model.effort:
        command += ["-c", f"model_reasoning_effort={model.effort}"]
    command += [
        "--skip-git-repo-check", "-s", "read-only", "--json",
        "-C", str(workspace), "-o", str(last_message),
        "-c", f'mcp_servers.prism.url="http://127.0.0.1:{port}/mcp"',
        "-c", 'mcp_servers.prism.bearer_token_env_var="PRISM_BOARD_TOKEN"',
        "-",
    ]
    return command


def _shown(command: Sequence[str], executable: Path) -> str:
    """The command as saved in the metadata: the executable by name, an empty argument as ``""``."""

    parts = [part if part else '""' for part in command]
    return " ".join(parts).replace(str(executable), executable.name)


def run_host(
    *,
    host: str,
    run_kind: str,
    prompt: str,
    token: str,
    model: HostModel,
    executable: Path,
    workspace: Path,
    port: int,
    work: Path,
    timeout_s: float,
    base_name: str,
    tokens: TokenRegistry,
    transcripts_dir: Path,
) -> HostRun:
    """One host launch. Saves sanitized stdout, stderr, prompt and metadata under ``transcripts_dir``."""

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    env = clean_env({"PRISM_BOARD_TOKEN": token})
    last_message = work / f"{base_name}.last-message.txt"
    if host == "claude":
        config_path = work / "claude-mcp.json"
        config_path.write_text(json.dumps(claude_mcp_config(port), indent=2) + "\n", encoding="utf-8")
        command = claude_command(executable, model, config_path)
    else:
        command = codex_command(executable, model, workspace, last_message, port)
    result = run_captured(command, cwd=workspace, env=env, stdin_text=prompt, timeout=timeout_s)

    if host == "claude":
        transcript = parse_claude_stream(result.stdout)
        efforts = claude_session_efforts(transcript.session_id)
        models = transcript.models | claude_session_models(transcript.session_id)
        models.discard("")
    else:
        message = last_message.read_text(encoding="utf-8", errors="replace") if last_message.exists() else None
        transcript = parse_codex_stream(result.stdout, message)
        models, efforts = codex_rollout_model_effort(transcript.session_id)
        models = models or transcript.models

    stdout = tokens.redact(result.stdout)
    stderr = tokens.redact(result.stderr)
    suffix = "jsonl"
    (transcripts_dir / f"{base_name}.{host}.stdout.{suffix}").write_text(stdout, encoding="utf-8", newline="\n")
    (transcripts_dir / f"{base_name}.{host}.stderr.txt").write_text(stderr, encoding="utf-8", newline="\n")
    (transcripts_dir / f"{base_name}.prompt.txt").write_text(tokens.redact(prompt), encoding="utf-8", newline="\n")
    (transcripts_dir / f"{base_name}.last-message.txt").write_text(tokens.redact(transcript.final_message), encoding="utf-8", newline="\n")
    shown = _shown(command, executable)
    meta = {
        "name": base_name,
        "host": host,
        "run": run_kind,
        "exit": result.exit_code,
        "timed_out": result.timed_out,
        "elapsed_s": result.elapsed_s,
        "command": tokens.redact(shown),
        "session_id": transcript.session_id,
        "recorded_models": sorted(models),
        "recorded_efforts": sorted(efforts),
    }
    (transcripts_dir / f"{base_name}.meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    return HostRun(host, run_kind, shown, result, transcript, models, efforts)
