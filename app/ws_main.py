from __future__ import annotations

import asyncio
from types import SimpleNamespace

import lark_oapi as lark

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


def create_host() -> SimpleNamespace:
    settings = load_settings()
    if not settings.app_id or not settings.app_secret:
        raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET are required for ws mode")

    exec_workdir = resolve_exec_workdir(settings.exec_workdir)
    exec_workdir_aliases, exec_workdir_allowlist = resolve_exec_workdirs(settings.exec_workdirs)
    exec_workdir = choose_default_exec_workdir(
        exec_workdir,
        exec_workdir_aliases,
        exec_workdir_allowlist,
    )
    if exec_workdir:
        exec_workdir_allowlist.add(exec_workdir)
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

    state = SimpleNamespace(
        settings=settings,
        store=store,
        runner=runner,
        feishu=feishu,
        queue=queue,
        exec_workdir=exec_workdir,
        exec_workdir_aliases=exec_workdir_aliases,
        exec_workdir_allowlist=exec_workdir_allowlist,
        loop=asyncio.get_event_loop(),
    )
    return SimpleNamespace(state=state)


def main() -> None:
    host = create_host()
    settings = host.state.settings
    loop = host.state.loop

    for _ in range(settings.queue_concurrency):
        loop.create_task(job_worker(host))

    def on_message_receive(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        loop.create_task(process_message_event(host, data))

    # Long-connection mode handles transport/auth/encryption internally.
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message_receive)
        .build()
    )

    client = lark.ws.Client(
        settings.app_id,
        settings.app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    client.start()


if __name__ == "__main__":
    main()
