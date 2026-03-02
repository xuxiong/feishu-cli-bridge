from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any


class StateStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.events_path = self.data_dir / "events.json"
        self.pending_path = self.data_dir / "pending_jobs.json"
        self.jobs_path = self.data_dir / "jobs.json"
        self.logs_dir = self.data_dir / "logs"
        self.runtime_dir = self.data_dir / "runtime"
        self._lock = asyncio.Lock()

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        self.events: dict[str, int] = self._read_json(self.events_path, {})
        self.pending: dict[str, dict[str, Any]] = self._read_json(self.pending_path, {})
        self.jobs: dict[str, dict[str, Any]] = self._read_json(self.jobs_path, {})

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        temp.replace(path)

    async def is_duplicate_event(self, event_id: str) -> bool:
        async with self._lock:
            return event_id in self.events

    async def mark_event(self, event_id: str, now_ts: int) -> None:
        async with self._lock:
            self.events[event_id] = now_ts
            self._write_json(self.events_path, self.events)

    async def mark_event_if_new(self, event_id: str, now_ts: int) -> bool:
        async with self._lock:
            if event_id in self.events:
                return False
            self.events[event_id] = now_ts
            self._write_json(self.events_path, self.events)
            return True

    async def cleanup_events(self, now_ts: int, keep_seconds: int) -> None:
        cutoff = now_ts - keep_seconds
        async with self._lock:
            original = len(self.events)
            self.events = {k: v for k, v in self.events.items() if v >= cutoff}
            if len(self.events) != original:
                self._write_json(self.events_path, self.events)

    async def create_pending(self, job: dict[str, Any]) -> None:
        async with self._lock:
            self.pending[job["job_id"]] = job
            self._write_json(self.pending_path, self.pending)

    async def get_pending(self, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return self.pending.get(job_id)

    async def remove_pending(self, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            job = self.pending.pop(job_id, None)
            self._write_json(self.pending_path, self.pending)
            return job

    async def expire_pending(self, now_ts: int) -> int:
        async with self._lock:
            to_delete = [
                job_id
                for job_id, payload in self.pending.items()
                if int(payload.get("expires_at", 0)) <= now_ts
            ]
            for job_id in to_delete:
                del self.pending[job_id]
            if to_delete:
                self._write_json(self.pending_path, self.pending)
            return len(to_delete)

    async def create_job(self, job: dict[str, Any]) -> None:
        async with self._lock:
            self.jobs[job["job_id"]] = job
            self._write_json(self.jobs_path, self.jobs)

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return self.jobs.get(job_id)

    async def update_job(self, job_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        async with self._lock:
            if job_id not in self.jobs:
                return None
            self.jobs[job_id].update(patch)
            self._write_json(self.jobs_path, self.jobs)
            return self.jobs[job_id]

    async def get_log_tail(self, job_id: str, max_chars: int = 5000) -> str:
        log_path = self.logs_dir / f"{job_id}.log"
        if not log_path.exists():
            return ""
        content = log_path.read_text(encoding="utf-8", errors="replace")
        return content[-max_chars:]

    async def get_last_jobs(self, count: int = 5) -> list[dict[str, Any]]:
        async with self._lock:
            jobs = list(self.jobs.values())
        jobs.sort(key=lambda x: int(x.get("created_at", 0)), reverse=True)
        return jobs[:count]

    @staticmethod
    def now_ts() -> int:
        return int(time.time())
