from __future__ import annotations

import json
import time
from typing import Any

import httpx


class FeishuClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        api_base: str,
        dry_run: bool = False,
        http_trust_env: bool = False,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.api_base = api_base.rstrip("/")
        self.dry_run = dry_run
        self.http_trust_env = http_trust_env
        self._token: str = ""
        self._token_expire_at: int = 0

    async def _get_tenant_access_token(self) -> str:
        now = int(time.time())
        if self._token and now < self._token_expire_at - 30:
            return self._token

        if not self.app_id or not self.app_secret:
            raise RuntimeError("missing FEISHU_APP_ID/FEISHU_APP_SECRET")

        url = f"{self.api_base}/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }
        async with httpx.AsyncClient(timeout=15.0, trust_env=self.http_trust_env) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"failed to get tenant_access_token: {data}")

        self._token = data["tenant_access_token"]
        expire = int(data.get("expire", 7200))
        self._token_expire_at = now + expire
        return self._token

    async def send_text(self, chat_id: str, text: str) -> dict[str, Any]:
        if self.dry_run:
            print(f"[DRY_RUN] chat_id={chat_id} text={text}")
            return {"code": 0, "msg": "dry_run"}

        token = await self._get_tenant_access_token()
        url = f"{self.api_base}/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        params = {"receive_id_type": "chat_id"}

        async with httpx.AsyncClient(timeout=15.0, trust_env=self.http_trust_env) as client:
            resp = await client.post(url, headers=headers, params=params, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"send message failed: {data}")
        return data
