#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$HOME/ict-trade-desk}"

echo "[1/4] Creating project at: $PROJECT_DIR"
mkdir -p "$PROJECT_DIR"

if [ ! -d "$PROJECT_DIR/.git" ]; then
  echo "[2/4] Initializing git repository"
  git -C "$PROJECT_DIR" init >/dev/null
fi

echo "[3/4] Copying frontend starter kit"
cp -R ./frontend/. "$PROJECT_DIR/"

cat <<MSG
[4/4] Starter ready.
Next:
  cd "$PROJECT_DIR"
  npm install
  npm run dev
MSG
