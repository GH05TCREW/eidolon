#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 is required but was not found on PATH." >&2
    exit 1
  fi
}

require_cmd docker
require_cmd npm

echo "Starting database containers..."
docker compose up -d

if command -v python >/dev/null 2>&1; then
  py_cmd="python"
elif command -v python3 >/dev/null 2>&1; then
  py_cmd="python3"
else
  echo "python (or python3) is required but was not found on PATH." >&2
  exit 1
fi

venv_path="$repo_root/venv"
python_exe="$venv_path/bin/python"
if [ ! -x "$python_exe" ]; then
  echo "Creating virtual environment..."
  "$py_cmd" -m venv "$venv_path"
fi

if ! "$python_exe" -c "import fastapi, uvicorn, psycopg, neo4j" 2>&1 >/dev/null; then
  echo "Installing Python dependencies..."
  "$python_exe" -m pip install --upgrade pip
  if ! "$python_exe" -m pip install -e .; then
    echo "Failed to install Python dependencies. Check the output above." >&2
    exit 1
  fi
fi

ui_dir="$repo_root/eidolon/ui"
if [ ! -d "$ui_dir/node_modules" ]; then
  echo "Installing UI dependencies..."
  (cd "$ui_dir" && npm install)
fi

echo "Starting API server..."
"$python_exe" -m uvicorn eidolon.api.app:app --reload --port 8080 &
api_pid=$!

echo "Starting UI dev server..."
(cd "$ui_dir" && npm run dev) &
ui_pid=$!

cleanup() {
  echo "Stopping..."
  kill "$api_pid" "$ui_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM
wait "$api_pid" "$ui_pid"
