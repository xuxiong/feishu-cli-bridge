#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo ".env created from .env.example"
fi

echo "Setup complete. Run: source .venv/bin/activate && ./scripts/run_ws.sh (recommended) or ./scripts/run_dev.sh"
