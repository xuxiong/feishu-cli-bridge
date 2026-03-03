# feishu-cli-bridge

Run approved local CLI tasks (`codex` / `gemini` / `qwen` / `codefree` / `claude`) from Feishu bot messages.

## Modes

### 1) Long Connection (Recommended)
Uses official Feishu SDK long connection (`lark.ws.Client`).
No public callback URL, no cloudflared/ngrok.

Start:

```bash
cd ~/feishu-cli-bridge
source .venv/bin/activate
./scripts/run_ws.sh
```

Feishu subscription mode: **Use long connection to receive callbacks**.

### 2) Webhook (Optional)
Uses official Feishu SDK `EventDispatcherHandler` on `POST /webhook`.
Only use this if you explicitly need callback URL mode.

Start:

```bash
cd ~/feishu-cli-bridge
source .venv/bin/activate
./scripts/run_dev.sh
```

Then expose `http://127.0.0.1:8787` and configure:

`https://<your-domain>/webhook`

## Supported Bot Commands

- `codex <task>` (also supports `/codex <task>`)
- `gemini <task>` (also supports `/gemini <task>`)
- `qwen <task>` (also supports `/qwen <task>`)
- `codefree <task>` (also supports `/codefree <task>`)
- `claude <task>` (also supports `/claude <task>`)
- `<runner> --workdir <alias|/abs/path> <task>` (optional, per-job workdir override)
- `/cancel <job_id>`
- `/logs <job_id>`

## Security Controls

- Fixed command prefixes only (no raw shell eval).
- Optional fixed execution directory: `EXEC_WORKDIR`.
- Optional multi-directory allowlist: `EXEC_WORKDIRS`.
- Optional directory-switch blocking: `DISALLOW_DIR_SWITCH=true`.
- Optional dangerous-operation blocking: `DISALLOW_DANGEROUS_TASK=true`.
- Cancel queued jobs (`/cancel <job_id>`).
- Event dedupe by `event_id`.

## Setup

```bash
cd ~/feishu-cli-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Key Env Vars

- `FEISHU_APP_ID`, `FEISHU_APP_SECRET`: required for both modes.
- `FEISHU_VERIFICATION_TOKEN`: required only for webhook mode.
- `FEISHU_ENCRYPT_KEY`: optional for webhook mode encrypted callback.
- `FEISHU_HTTP_TRUST_ENV`: defaults to `false`; set `true` only if you intentionally want to use system proxy env vars.
- `CODEX_COMMAND`, `GEMINI_COMMAND`, `QWEN_COMMAND`, `CODEFREE_COMMAND`, `CLAUDE_COMMAND`.
- `EXEC_WORKDIR`, `EXEC_WORKDIRS`, `DISALLOW_DIR_SWITCH`, `DISALLOW_DANGEROUS_TASK`.

`EXEC_WORKDIRS` format example:

```bash
EXEC_WORKDIRS="bridge=/Users/apple/feishu-cli-bridge,codefree=/Users/apple/owork/srdcloud/codefree-cli,/tmp"
```

If `EXEC_WORKDIR` is empty but `EXEC_WORKDIRS` is set, the default workdir becomes:
- the first alias in lexical order, otherwise
- the first path in lexical order.

Use in chat:

```text
codex --workdir bridge 修复登录接口超时问题
codex --workdir /Users/apple/feishu-cli-bridge 更新 README
```

Recommended non-interactive + auto-approval mapping:

```bash
CODEX_COMMAND="codex exec --full-auto"
GEMINI_COMMAND="gemini -p --approval-mode yolo"
QWEN_COMMAND="qwen --approval-mode yolo"
CODEFREE_COMMAND="codefree --approval-mode yolo"
CLAUDE_COMMAND="claude -p --permission-mode bypassPermissions"
```

## Data Files

- `data/events.json`: processed event IDs.
- `data/jobs.json`: queued/running/completed jobs.
- `data/logs/<job_id>.log`: full CLI output.
- `data/runtime/<job_id>.exit`: exit code.
