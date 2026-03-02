from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Any


class TmuxRunner:
    def __init__(self, logs_dir: Path, runtime_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.runtime_dir = runtime_dir

    async def run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = job["job_id"]
        session_name = f"bot-{job_id[:12]}"
        log_path = self.logs_dir / f"{job_id}.log"
        exit_path = self.runtime_dir / f"{job_id}.exit"

        if exit_path.exists():
            exit_path.unlink()

        cmd_list = job["command"]
        cmd_line = shlex.join(cmd_list)
        workdir = str(job.get("workdir", "")).strip()
        cd_prefix = f"cd {shlex.quote(workdir)} && " if workdir else ""

        # Execute in detached tmux session and persist output for /logs.
        inner = (
            f"set -o pipefail; "
            f"{cd_prefix}{cmd_line} > {shlex.quote(str(log_path))} 2>&1; "
            f"code=$?; "
            f"echo $code > {shlex.quote(str(exit_path))}; "
            f"exit $code"
        )

        await self._run_cmd("tmux", "new-session", "-d", "-s", session_name, "bash", "-lc", inner)

        while not exit_path.exists():
            await asyncio.sleep(1)

        exit_code = int(exit_path.read_text(encoding="utf-8").strip() or "1")
        output = ""
        if log_path.exists():
            output = log_path.read_text(encoding="utf-8", errors="replace")

        await self._run_cmd("tmux", "kill-session", "-t", session_name, check=False)

        return {
            "job_id": job_id,
            "session_name": session_name,
            "exit_code": exit_code,
            "log_path": str(log_path),
            "output_tail": output[-5000:],
        }

    async def _run_cmd(self, *args: str, check: bool = True) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await proc.communicate()
        out = out_b.decode("utf-8", errors="replace")
        err = err_b.decode("utf-8", errors="replace")
        if check and proc.returncode != 0:
            raise RuntimeError(f"command failed ({args}): {proc.returncode}, stderr={err.strip()}")
        return proc.returncode, out, err
