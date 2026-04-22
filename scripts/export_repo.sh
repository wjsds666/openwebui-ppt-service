#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${1:-$HOME/Desktop/openwebui-ppt-service}"

mkdir -p "$DEST_DIR"

rsync -av \
  --exclude '.env' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'storage/jobs' \
  --exclude 'storage/exports' \
  --exclude 'storage/logs' \
  --exclude 'storage/runtime_config.json' \
  "$SRC_DIR/" "$DEST_DIR/"

echo "Exported standalone repo to: $DEST_DIR"
