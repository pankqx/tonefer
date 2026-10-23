#!/usr/bin/env bash
# Tonefer — one-click setup for Ubuntu.
#
#   ./scripts/install-ubuntu.sh                      # service + launcher + firewall
#   ./scripts/install-ubuntu.sh --hotspot "Pank's A54"  # also auto-join that hotspot
#
# What it does (all reversible with ./scripts/uninstall-ubuntu.sh):
#   1. Creates a private Python environment in .venv
#   2. Runs Tonefer in the background whenever you log in (systemd user service)
#   3. Adds "Tonefer" to your app launcher (opens as its own window)
#   4. Opens the firewall port if Ubuntu's firewall (ufw) is on
#   5. Optionally makes the laptop join your phone's hotspot automatically
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${TONEFER_PORT:-8765}"
HOTSPOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --hotspot) HOTSPOT="${2:-}"; shift 2 ;;
    --port) PORT="${2:-8765}"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  [x] %s\n' "$*"; }
skip() { printf '  [ ] %s\n' "$*"; }

bold "Tonefer setup"
echo

# 1 — Python environment ---------------------------------------------------
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  if ! python3 -m venv "$ROOT/.venv" 2>/dev/null; then
    echo "Python's venv module is missing. Install it with:"
    echo "  sudo apt install -y python3-venv"
    exit 1
  fi
fi
"$ROOT/.venv/bin/pip" install -q --upgrade pip
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
ok "Python environment ready"

# 2 — background service -------------------------------------------------
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/tonefer.service" <<UNIT
[Unit]
Description=Tonefer — phone ⇄ laptop transfer
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
Environment=TONEFER_PORT=$PORT
ExecStart=$ROOT/.venv/bin/python $ROOT/server.py --no-browser
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now tonefer.service >/dev/null 2>&1
systemctl --user restart tonefer.service
ok "Runs in the background at every login (systemd user service)"

# 3 — app launcher ---------------------------------------------------------
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons"
mkdir -p "$APPS" "$ICONS"
cp "$ROOT/web/static/icon.svg" "$ICONS/tonefer.svg"
chmod +x "$ROOT/scripts/open.sh"
cat > "$APPS/tonefer.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Tonefer
GenericName=Phone transfer
Comment=Send notes, photos and files between your phone and this laptop
Exec=$ROOT/scripts/open.sh
Icon=$ICONS/tonefer.svg
Terminal=false
Categories=Utility;Network;FileTransfer;
Keywords=phone;transfer;share;photos;android;
StartupWMClass=tonefer
DESK
update-desktop-database "$APPS" >/dev/null 2>&1 || true
ok "\"Tonefer\" added to your app launcher (press Super, type Tonefer)"

# 4 — firewall -------------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && [ "$(systemctl is-active ufw 2>/dev/null)" = "active" ]; then
  echo "    Ubuntu's firewall is on. Opening port $PORT (asks for your password)…"
  if sudo ufw allow "$PORT/tcp" comment tonefer >/dev/null; then
    ok "Firewall: port $PORT open"
  else
    skip "Firewall: could not open port. Run: sudo ufw allow $PORT/tcp"
  fi
else
  ok "Firewall: nothing to change"
fi

# 5 — hotspot auto-join -----------------------------------------------------
if command -v nmcli >/dev/null 2>&1; then
  if [ -z "$HOTSPOT" ] && [ -t 0 ]; then
    echo
    echo "    Saved Wi-Fi networks:"
    nmcli -t -f NAME,TYPE connection show | awk -F: '$2=="802-11-wireless"{print "      - "$1}'
    read -r -p "    Name of your phone's hotspot to auto-join (Enter to skip): " HOTSPOT
  fi
  if [ -n "$HOTSPOT" ]; then
    if nmcli connection modify "$HOTSPOT" connection.autoconnect yes connection.autoconnect-priority 50 2>/dev/null; then
      # Tonefer's watcher also switches over from other Wi-Fi as soon as the hotspot appears.
      mkdir -p "$HOME/.tonefer"
      "$ROOT/.venv/bin/python" - "$HOTSPOT" <<'PY'
import json, sys, pathlib
p = pathlib.Path.home() / ".tonefer" / "config.json"
try:
    data = json.loads(p.read_text())
except Exception:
    data = {}
data.update(hotspot=sys.argv[1], auto_join=True)
p.write_text(json.dumps(data, indent=2))
PY
      systemctl --user restart tonefer.service 2>/dev/null || true
      ok "Laptop auto-joins \"$HOTSPOT\" whenever it's on, even from other Wi-Fi"
    else
      skip "Couldn't find \"$HOTSPOT\". Join it once from the Wi-Fi menu, then re-run with --hotspot \"$HOTSPOT\""
    fi
  else
    skip "Hotspot auto-join skipped (re-run with --hotspot \"Name\")"
  fi
fi

echo
bold "Done."
echo "  Open Tonefer from your app launcher, or visit http://127.0.0.1:$PORT/desk"
echo "  Everyday use: turn on the phone's hotspot, then tap Tonefer on the phone."
