from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_id: str
    app_secret: str
    verification_token: str
    encrypt_key: str
    api_base: str
    http_trust_env: bool
    host: str
    port: int
    data_dir: Path
    replay_window_seconds: int
    pending_ttl_seconds: int
    max_task_length: int
    codex_command: str
    gemini_command: str
    qwen_command: str
    codefree_command: str
    claude_command: str
    exec_workdir: str
    exec_workdirs: str
    disallow_dir_switch: bool
    disallow_dangerous_task: bool
    queue_concurrency: int
    dry_run: bool


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    home = Path(os.getenv("HOME", "/tmp"))
    default_data = home / "feishu-cli-bridge-data"
    return Settings(
        app_id=os.getenv("FEISHU_APP_ID", ""),
        app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
        encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY", ""),
        api_base=os.getenv("FEISHU_API_BASE", "https://open.feishu.cn"),
        http_trust_env=_env_bool("FEISHU_HTTP_TRUST_ENV", default=False),
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "8787")),
        data_dir=Path(os.getenv("DATA_DIR", str(default_data))),
        replay_window_seconds=int(os.getenv("REPLAY_WINDOW_SECONDS", "300")),
        pending_ttl_seconds=int(os.getenv("PENDING_TTL_SECONDS", "300")),
        max_task_length=int(os.getenv("MAX_TASK_LENGTH", "1500")),
        codex_command=os.getenv("CODEX_COMMAND", "codex"),
        gemini_command=os.getenv("GEMINI_COMMAND", "gemini"),
        qwen_command=os.getenv("QWEN_COMMAND", "qwen"),
        codefree_command=os.getenv("CODEFREE_COMMAND", "codefree"),
        claude_command=os.getenv("CLAUDE_COMMAND", "claude"),
        exec_workdir=os.getenv("EXEC_WORKDIR", ""),
        exec_workdirs=os.getenv("EXEC_WORKDIRS", ""),
        disallow_dir_switch=_env_bool("DISALLOW_DIR_SWITCH", default=True),
        disallow_dangerous_task=_env_bool("DISALLOW_DANGEROUS_TASK", default=True),
        queue_concurrency=max(1, int(os.getenv("QUEUE_CONCURRENCY", "1"))),
        dry_run=_env_bool("DRY_RUN", default=False),
    )
