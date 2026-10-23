#!/usr/bin/env bash
# Opens the Tonefer window. Starts the background service first if needed.
PORT="${TONEFER_PORT:-8765}"
URL="http://127.0.0.1:$PORT/desk"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! curl -fs -o /dev/null "$URL" 2>/dev/null; then
  if systemctl --user list-unit-files tonefer.service >/dev/null 2>&1; then
    systemctl --user start tonefer.service
  else
    (cd "$ROOT" && nohup .venv/bin/python server.py --no-browser >/dev/null 2>&1 &)
  fi
  for _ in $(seq 1 30); do curl -fs -o /dev/null "$URL" && break; sleep 0.2; done
fi

# Prefer a clean app window (no tabs or address bar) when a Chromium browser exists.
for b in google-chrome google-chrome-stable chromium chromium-browser brave-browser microsoft-edge; do
  if command -v "$b" >/dev/null 2>&1; then
    exec "$b" --app="$URL" --class=tonefer --window-size=1280,820 >/dev/null 2>&1
  fi
done
exec xdg-open "$URL"
