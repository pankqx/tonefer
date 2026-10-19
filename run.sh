#!/usr/bin/env bash
# Start tonefer on Linux/macOS. First run sets up a private virtual environment.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Setting up tonefer (first run)…"
  if ! python3 -m venv .venv 2>/dev/null; then
    echo "Python venv support is missing. On Ubuntu run:  sudo apt install python3-venv"
    exit 1
  fi
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python server.py "$@"
