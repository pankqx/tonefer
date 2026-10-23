#!/usr/bin/env bash
# Start tonefer on Linux/macOS. First run sets up a private virtual environment.
set -e
cd "$(dirname "$0")"
PORT="${TONEFER_PORT:-8765}"

if [ ! -x .venv/bin/python ]; then
  echo "Setting up tonefer (first run)…"
  if ! python3 -m venv .venv 2>/dev/null; then
    echo "Python venv support is missing. On Ubuntu run:  sudo apt install python3-venv"
    exit 1
  fi
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

# Ubuntu's firewall silently drops the phone's connection ("site can't be reached").
if command -v ufw >/dev/null 2>&1 && [ "$(systemctl is-active ufw 2>/dev/null)" = "active" ] \
   && [ ! -f .venv/.ufw-ok-$PORT ]; then
  echo
  echo "Ubuntu's firewall is on, so your phone can't reach tonefer yet."
  read -r -p "Allow port $PORT through it now? (asks for your password) [Y/n] " ans
  if [ -z "$ans" ] || [[ "$ans" =~ ^[Yy] ]]; then
    sudo ufw allow "$PORT/tcp" comment tonefer && touch ".venv/.ufw-ok-$PORT"
  else
    echo "Skipped. Run later:  sudo ufw allow $PORT/tcp"
  fi
fi

if [ "$1" = "doctor" ]; then exec .venv/bin/python server.py --doctor; fi
exec .venv/bin/python server.py "$@"
