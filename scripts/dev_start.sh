#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH="$ROOT_DIR"
uvicorn app.api.main:app --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8099}" --reload
