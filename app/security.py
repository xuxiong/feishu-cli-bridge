from __future__ import annotations

import json
import re
import time
from fastapi import HTTPException


DEFAULT_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"(^|[\s;&|`])sudo(\s|$)", "sudo"),
    (r"rm\s+-[^\n]*r[^\n]*f[^\n]*\s+/", "rm-rf-root"),
    (r"rm\s+-[^\n]*r[^\n]*f[^\n]*\s+~", "rm-rf-home"),
    (r"(^|[\s;&|`])mkfs(\.|[\s])", "mkfs"),
    (r"(^|[\s;&|`])dd\s+if=", "dd-if"),
    (r"(^|[\s;&|`])(shutdown|reboot|halt|poweroff)(\s|$)", "shutdown-reboot"),
    (r"(^|[\s;&|`])kill\s+-9\s+1(\s|$)", "kill-init"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", "fork-bomb"),
    (r"(curl|wget)[^\n]*(\||\|\s+)(sh|bash|zsh)(\s|$)", "download-and-exec"),
]

def ensure_create_time(create_time_ms: str | int | None, replay_window_seconds: int) -> None:
    if create_time_ms is None:
        return
    try:
        create_ts = int(int(create_time_ms) / 1000)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid create_time") from exc

    now_ts = int(time.time())
    if abs(now_ts - create_ts) > replay_window_seconds:
        raise HTTPException(status_code=401, detail="stale request timestamp")


def extract_text_from_message(message: dict[str, Any]) -> str:
    if message.get("message_type") != "text":
        return ""
    raw_content = message.get("content", "")
    if not raw_content:
        return ""
    try:
        content_obj = json.loads(raw_content)
        text = content_obj.get("text", "")
    except Exception:
        text = raw_content

    text = re.sub(r"<at\b[^>]*>.*?</at>", "", text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()


def validate_task(task: str, max_length: int) -> None:
    if not task:
        raise HTTPException(status_code=400, detail="empty task")
    if len(task) > max_length:
        raise HTTPException(status_code=400, detail=f"task too long; max={max_length}")

    for ch in task:
        code = ord(ch)
        if code < 32 and ch not in {"\t", " "}:
            raise HTTPException(status_code=400, detail="task contains control characters")


def validate_no_directory_switch(task: str) -> None:
    patterns = [
        r"(^|[\s;&|`])cd\s+",
        r"(^|[\s;&|`])pushd\s+",
        r"(^|[\s;&|`])popd(\s|$)",
        r"\bchdir\s*\(",
    ]
    for pattern in patterns:
        if re.search(pattern, task, flags=re.IGNORECASE):
            raise HTTPException(status_code=400, detail="directory switching is not allowed in run task")


def validate_no_dangerous_ops(task: str) -> None:
    for pattern, label in DEFAULT_DANGEROUS_PATTERNS:
        if re.search(pattern, task, flags=re.IGNORECASE):
            raise HTTPException(
                status_code=400,
                detail=f"dangerous operation is not allowed in run task: {label}",
            )
