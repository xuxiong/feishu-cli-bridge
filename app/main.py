from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import lark_oapi as lark
from fastapi import FastAPI, Request, Response
from lark_oapi.core.model import RawRequest

from app.bridge_core import (
    choose_default_exec_workdir,
    job_worker,
    process_message_event,
    resolve_exec_workdir,
    resolve_exec_workdirs,
)
from app.config import load_settings
from app.feishu_client import FeishuClient
from app.runner import TmuxRunner
from app.store import StateStore


def create_app() -> FastAPI:
    app = FastAPI(title="feishu-cli-bridge", version="0.3.0")
    settings = load_settings()
    exec_workdir = resolve_exec_workdir(settings.exec_workdir)
    exec_workdir_aliases, exec_workdir_allowlist = resolve_exec_workdirs(settings.exec_workdirs)
    exec_workdir = choose_default_exec_workdir(
        exec_workdir,
        exec_workdir_aliases,
        exec_workdir_allowlist,
    )
    if exec_workdir:
        exec_workdir_allowlist.add(exec_workdir)

    if not settings.verification_token:
        raise RuntimeError("FEISHU_VERIFICATION_TOKEN is required for webhook mode")

    store = StateStore(settings.data_dir)
    runner = TmuxRunner(store.logs_dir, store.runtime_dir)
    feishu = FeishuClient(
        app_id=settings.app_id,
        app_secret=settings.app_secret,
        api_base=settings.api_base,
        dry_run=settings.dry_run,
        http_trust_env=settings.http_trust_env,
    )

    queue: asyncio.Queue[str] = asyncio.Queue()
    workers: list[asyncio.Task[Any]] = []

    app.state.settings = settings
    app.state.store = store
    app.state.runner = runner
    app.state.feishu = feishu
    app.state.queue = queue
    app.state.exec_workdir = exec_workdir
    app.state.exec_workdir_aliases = exec_workdir_aliases
    app.state.exec_workdir_allowlist = exec_workdir_allowlist
    app.state.loop = None

    def on_message_receive(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        loop = app.state.loop
        if loop and loop.is_running():
            loop.create_task(process_message_event(app, data))
            return

        try:
            running_loop = asyncio.get_running_loop()
            running_loop.create_task(process_message_event(app, data))
        except RuntimeError:
            asyncio.run(process_message_event(app, data))

    event_handler = (
        lark.EventDispatcherHandler.builder(
            settings.encrypt_key,
            settings.verification_token,
        )
        .register_p2_im_message_receive_v1(on_message_receive)
        .build()
    )
    app.state.event_handler = event_handler

    @app.on_event("startup")
    async def startup() -> None:
        app.state.loop = asyncio.get_running_loop()
        for _ in range(settings.queue_concurrency):
            workers.append(asyncio.create_task(job_worker(app), name="job-worker"))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        for task in workers:
            task.cancel()
        for task in workers:
            with suppress(asyncio.CancelledError):
                await task

    @app.get("/health")
    async def health() -> dict[str, Any]:
        recent = await store.get_last_jobs(3)
        return {
            "ok": True,
            "queue_size": queue.qsize(),
            "recent_jobs": [
                {"job_id": item.get("job_id"), "status": item.get("status")} for item in recent
            ],
        }

    @app.post("/webhook")
    async def webhook(request: Request) -> Response:
        body = await request.body()
        raw_req = RawRequest()
        raw_req.uri = request.url.path
        raw_req.body = body
        raw_req.headers = {key: value for key, value in request.headers.items()}

        raw_resp = event_handler.do(raw_req)
        return Response(
            content=raw_resp.content or b"",
            status_code=raw_resp.status_code or 200,
            headers=raw_resp.headers,
        )

    return app


app = create_app()
