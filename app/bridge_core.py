from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any

import lark_oapi as lark
from fastapi import HTTPException

from app.command_router import (
    build_command,
    help_text,
    normalize_job_id,
    parse_command,
    validate_job_id,
)
from app.config import Settings
from app.feishu_client import FeishuClient
from app.runner import TmuxRunner
from app.security import (
    ensure_create_time,
    extract_text_from_message,
    validate_no_dangerous_ops,
    validate_no_directory_switch,
    validate_task,
)
from app.store import StateStore

WORKDIR_ALIAS_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$", flags=re.IGNORECASE)
WORKDIR_TASK_PREFIX_PATTERN = re.compile(
    r"^(?:--(?:workdir|cwd))\s+(\S+)\s+(.+)$",
    flags=re.IGNORECASE | re.DOTALL,
)


def _preview_text(value: str, limit: int = 180) -> str:
    cleaned = (value or "").replace("\n", "\\n")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."


def _resolve_directory(path_text: str, env_name: str) -> str:
    path = Path(path_text).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise RuntimeError(f"{env_name} is invalid: {path}")
    return str(path)


def resolve_exec_workdir(raw_workdir: str) -> str:
    value = (raw_workdir or "").strip()
    if not value:
        return ""
    return _resolve_directory(value, "EXEC_WORKDIR")


def resolve_exec_workdirs(raw_workdirs: str) -> tuple[dict[str, str], set[str]]:
    aliases: dict[str, str] = {}
    allowlist: set[str] = set()
    value = (raw_workdirs or "").strip()
    if not value:
        return aliases, allowlist

    for token in value.split(","):
        entry = token.strip()
        if not entry:
            continue
        alias = ""
        path_text = entry
        if "=" in entry:
            left, right = entry.split("=", 1)
            alias = left.strip().lower()
            path_text = right.strip()
            if not alias:
                raise RuntimeError("EXEC_WORKDIRS has empty alias")
            if not WORKDIR_ALIAS_PATTERN.fullmatch(alias):
                raise RuntimeError(f"EXEC_WORKDIRS alias is invalid: {alias}")

        resolved = _resolve_directory(path_text, "EXEC_WORKDIRS")
        allowlist.add(resolved)
        if alias:
            existing = aliases.get(alias)
            if existing and existing != resolved:
                raise RuntimeError(f"EXEC_WORKDIRS alias conflicts: {alias}")
            aliases[alias] = resolved

    return aliases, allowlist


def choose_default_exec_workdir(
    default_workdir: str,
    aliases: dict[str, str],
    allowlist: set[str],
) -> str:
    if default_workdir:
        return default_workdir
    if aliases:
        first_alias = sorted(aliases.keys())[0]
        return aliases[first_alias]
    if allowlist:
        return sorted(allowlist)[0]
    return ""


def extract_workdir_selector(task: str) -> tuple[str, str]:
    value = (task or "").strip()
    if not value:
        return "", ""
    match = WORKDIR_TASK_PREFIX_PATTERN.match(value)
    if not match:
        return "", value
    selector = match.group(1).strip()
    stripped_task = match.group(2).strip()
    return selector, stripped_task


def pick_exec_workdir(
    selector: str,
    default_workdir: str,
    aliases: dict[str, str],
    allowlist: set[str],
) -> str:
    key = (selector or "").strip()
    if not key:
        return default_workdir

    alias = key.lower()
    if alias in aliases:
        return aliases[alias]

    resolved = str(Path(key).expanduser().resolve())
    if resolved in allowlist:
        return resolved

    if aliases:
        options = ", ".join(sorted(aliases.keys()))
        raise HTTPException(
            status_code=400,
            detail=f"workdir not allowed: {key}. allowed aliases: {options}",
        )
    raise HTTPException(
        status_code=400,
        detail=f"workdir not allowed: {key}. configure EXEC_WORKDIRS first",
    )


def build_runner_command(runner: str, task: str, settings: Settings) -> list[str]:
    if runner == "codex":
        return build_command(settings.codex_command, task)
    if runner == "gemini":
        return build_command(settings.gemini_command, task)
    if runner == "qwen":
        return build_command(settings.qwen_command, task)
    if runner == "codefree":
        return build_command(settings.codefree_command, task)
    if runner == "claude":
        return build_command(settings.claude_command, task)
    raise HTTPException(status_code=400, detail=f"unsupported runner: {runner}")


async def safe_send(feishu: FeishuClient, chat_id: str, text: str) -> None:
    if not chat_id:
        return
    try:
        await feishu.send_text(chat_id, text)
    except Exception as exc:
        print(f"send_text failed chat_id={chat_id}: {exc}")


async def process_message_event(host: Any, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    settings: Settings = host.state.settings
    store: StateStore = host.state.store
    feishu: FeishuClient = host.state.feishu
    queue: asyncio.Queue[str] = host.state.queue
    exec_workdir: str = host.state.exec_workdir
    exec_workdir_aliases: dict[str, str] = host.state.exec_workdir_aliases
    exec_workdir_allowlist: set[str] = host.state.exec_workdir_allowlist

    try:
        header = data.header
        if not header:
            return

        event_id = str(header.event_id or "").strip()
        if not event_id:
            return

        ensure_create_time(header.create_time, settings.replay_window_seconds)

        now_ts = store.now_ts()
        await store.cleanup_events(now_ts=now_ts, keep_seconds=settings.replay_window_seconds)
        if not await store.mark_event_if_new(event_id, now_ts):
            print(f"[feishu] duplicate event ignored: event_id={event_id}")
            return

        event = data.event
        if not event or not event.message:
            return

        message = event.message
        sender = event.sender
        message_type = message.message_type or ""
        chat_id = message.chat_id or ""
        text = extract_text_from_message(
            {
                "message_type": message_type,
                "content": message.content or "",
            }
        )
        user_id = "unknown"
        if sender and sender.sender_id:
            user_id = (
                sender.sender_id.open_id
                or sender.sender_id.user_id
                or sender.sender_id.union_id
                or "unknown"
            )
        log_preview = text or (message.content or "")
        print(
            f"[feishu] recv event_id={event_id} chat_id={chat_id} user_id={user_id} "
            f"message_type={message_type or 'unknown'} text={_preview_text(log_preview)}"
        )
        if not text:
            return

        parsed = parse_command(text)
        if parsed.action == "ignore":
            return

        if parsed.action == "help" or parsed.action == "unknown":
            await safe_send(feishu, chat_id, help_text())
            return

        if parsed.action == "logs":
            job_id = normalize_job_id(parsed.job_id)
            if not validate_job_id(job_id):
                await safe_send(feishu, chat_id, "invalid job_id")
                return
            tail = await store.get_log_tail(job_id)
            if not tail:
                await safe_send(feishu, chat_id, f"no logs for {job_id}")
            else:
                await safe_send(feishu, chat_id, f"logs for {job_id}:\n{tail}")
            return

        if parsed.action == "cancel":
            job_id = normalize_job_id(parsed.job_id)
            if not validate_job_id(job_id):
                await safe_send(feishu, chat_id, "invalid job_id")
                return

            job = await store.get_job(job_id)
            if not job:
                await safe_send(feishu, chat_id, f"job not found: {job_id}")
                return

            if job.get("requested_by") != user_id:
                await safe_send(feishu, chat_id, f"only the requester can manage job {job_id}")
                return

            status = str(job.get("status", ""))
            if status == "queued":
                await store.update_job(
                    job_id,
                    {
                        "status": "canceled",
                        "canceled_at": store.now_ts(),
                    },
                )
                await safe_send(feishu, chat_id, f"job canceled: {job_id}")
                return

            await safe_send(feishu, chat_id, f"job cannot be canceled in status: {status}")
            return

        if parsed.action == "submit":
            workdir_selector, run_task = extract_workdir_selector(parsed.task)
            workdir = pick_exec_workdir(
                workdir_selector,
                exec_workdir,
                exec_workdir_aliases,
                exec_workdir_allowlist,
            )
            validate_task(run_task, settings.max_task_length)
            if settings.disallow_dangerous_task:
                validate_no_dangerous_ops(run_task)
            if settings.disallow_dir_switch:
                validate_no_directory_switch(run_task)

            command = build_runner_command(parsed.runner, run_task, settings)
            now = store.now_ts()
            job_id = f"job-{uuid.uuid4().hex[:10]}"
            job = {
                "job_id": job_id,
                "status": "queued",
                "runner": parsed.runner,
                "task": run_task,
                "command": command,
                "workdir": workdir,
                "requested_by": user_id,
                "chat_id": chat_id,
                "created_at": now,
                "queued_at": now,
            }
            await store.create_job(job)
            await queue.put(job_id)
            await safe_send(
                feishu,
                chat_id,
                (
                    f"job queued: {job_id}\n"
                    f"runner: {parsed.runner}\n"
                    f"workdir: {workdir or '(no restriction)'}"
                ),
            )
    except HTTPException as exc:
        msg = getattr(exc, "detail", "invalid request")
        chat_id = ""
        try:
            if data.event and data.event.message:
                chat_id = data.event.message.chat_id or ""
        except Exception:
            chat_id = ""
        await safe_send(feishu, chat_id, str(msg))
    except Exception as exc:
        print(f"process_message_event failed: {exc}")


async def job_worker(host: Any) -> None:
    queue: asyncio.Queue[str] = host.state.queue
    store: StateStore = host.state.store
    runner: TmuxRunner = host.state.runner
    feishu: FeishuClient = host.state.feishu

    while True:
        job_id = await queue.get()
        try:
            job = await store.get_job(job_id)
            if not job:
                continue
            if str(job.get("status", "")) != "queued":
                continue

            await store.update_job(
                job_id,
                {
                    "status": "running",
                    "started_at": store.now_ts(),
                },
            )
            await safe_send(feishu, job.get("chat_id", ""), f"job running: {job_id}")

            result = await runner.run_job(job)
            status = "succeeded" if result["exit_code"] == 0 else "failed"
            await store.update_job(
                job_id,
                {
                    "status": status,
                    "finished_at": store.now_ts(),
                    "exit_code": result["exit_code"],
                    "log_path": result["log_path"],
                },
            )

            tail = result["output_tail"] or "<empty output>"
            message = (
                f"job finished: {job_id}\n"
                f"status: {status}\n"
                f"exit_code: {result['exit_code']}\n"
                f"tail:\n{tail}"
            )
            await safe_send(feishu, job.get("chat_id", ""), message)
        except Exception as exc:
            await store.update_job(
                job_id,
                {
                    "status": "error",
                    "finished_at": store.now_ts(),
                    "error": str(exc),
                },
            )
            job = await store.get_job(job_id)
            chat_id = ""
            if job:
                chat_id = job.get("chat_id", "")
            await safe_send(feishu, chat_id, f"job error: {job_id}, {exc}")
        finally:
            queue.task_done()
