from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedCommand:
    action: str
    runner: str = ""
    task: str = ""
    job_id: str = ""


def parse_command(text: str) -> ParsedCommand:
    value = text.strip()
    # Feishu long-connection text may include a plain-text mention prefix like "@_user_1 ".
    # Strip one or more leading mention tokens so slash commands can be recognized.
    value = re.sub(r"^(?:@\S+\s+)+", "", value).strip()
    if not value.startswith("/"):
        return ParsedCommand(action="ignore")

    submit_match = re.match(
        r"^/(codex|gemini|qwen|codefree|claude)\s+(?!run\b)(.+)$",
        value,
        flags=re.IGNORECASE,
    )
    if submit_match:
        runner = submit_match.group(1).lower()
        task = submit_match.group(2).strip()
        return ParsedCommand(action="submit", runner=runner, task=task)

    if value.startswith("/cancel "):
        return ParsedCommand(action="cancel", job_id=value[len("/cancel ") :].strip())
    if value.startswith("/logs "):
        return ParsedCommand(action="logs", job_id=value[len("/logs ") :].strip())
    if value == "/help":
        return ParsedCommand(action="help")

    return ParsedCommand(action="unknown")


def normalize_job_id(job_id: str) -> str:
    return job_id.strip().lower()


def validate_job_id(job_id: str) -> bool:
    return re.fullmatch(r"[a-z0-9\-]{6,64}", job_id or "") is not None


def build_command(base_command: str, task: str) -> list[str]:
    base_parts = shlex.split(base_command.strip())
    if not base_parts:
        raise ValueError("base command is empty")
    return [*base_parts, task]


def help_text() -> str:
    return "\n".join(
        [
            "Available commands:",
            "/codex <task>",
            "/gemini <task>",
            "/qwen <task>",
            "/codefree <task>",
            "/claude <task>",
            "/cancel <job_id>",
            "/logs <job_id>",
        ]
    )
