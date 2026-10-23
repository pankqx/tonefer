#!/usr/bin/env bash
# Removes what install-ubuntu.sh added. Your files in ~/Tonefer and pairing in ~/.tonefer are kept.
set -u
systemctl --user disable --now tonefer.service >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/tonefer.service"
systemctl --user daemon-reload 2>/dev/null || true
rm -f "$HOME/.local/share/applications/tonefer.desktop" "$HOME/.local/share/icons/tonefer.svg"
echo "  [x] Background service removed"
echo "  [x] App launcher entry removed"
echo
echo "Kept: ~/Tonefer (your files) and ~/.tonefer (history and pairing)."
echo "Firewall rule, if added, can be removed with: sudo ufw delete allow 8765/tcp"
echo "Hotspot auto-join can be turned off in Settings → Wi-Fi → (network) → Connect automatically."
