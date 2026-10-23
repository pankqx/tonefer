#!/usr/bin/env bash
# Builds dist/tonefer_<version>_all.deb — install with a double-click or: sudo apt install ./tonefer_*.deb
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
PKG="$ROOT/build/tonefer_${VERSION}_all"
rm -rf "$PKG" && mkdir -p "$PKG/DEBIAN" "$ROOT/dist"

# App files
install -d "$PKG/opt/tonefer/desktop"
cp "$ROOT/server.py" "$ROOT/netinfo.py" "$ROOT/VERSION" "$PKG/opt/tonefer/"
cp -r "$ROOT/web" "$PKG/opt/tonefer/"
cp "$ROOT/desktop/tonefer_app.py" "$PKG/opt/tonefer/desktop/"
find "$PKG/opt/tonefer" -name __pycache__ -prune -exec rm -rf {} +

# Command
install -d "$PKG/usr/bin"
cat > "$PKG/usr/bin/tonefer" <<'SH'
#!/bin/sh
exec /usr/bin/python3 /opt/tonefer/desktop/tonefer_app.py "$@"
SH
chmod 755 "$PKG/usr/bin/tonefer"

# Background service (starts at login for every user)
install -d "$PKG/usr/lib/systemd/user"
cat > "$PKG/usr/lib/systemd/user/tonefer.service" <<'UNIT'
[Unit]
Description=Tonefer — phone ⇄ laptop transfer
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/tonefer/server.py --no-browser
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT

# Launcher + icon
install -d "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/scalable/apps"
cp "$ROOT/web/static/icon.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/tonefer.svg"
cat > "$PKG/usr/share/applications/com.pankqx.Tonefer.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Tonefer
GenericName=Phone transfer
Comment=Send notes, photos and files between your phone and this laptop
Exec=tonefer
Icon=tonefer
Terminal=false
Categories=Utility;Network;FileTransfer;
Keywords=phone;transfer;share;photos;android;hotspot;
StartupWMClass=tonefer
StartupNotify=true
DESK

# Docs
install -d "$PKG/usr/share/doc/tonefer"
cp "$ROOT/README.md" "$ROOT/GUIDE.md" "$PKG/usr/share/doc/tonefer/"
cat > "$PKG/usr/share/doc/tonefer/copyright" <<'C'
Tonefer — Copyright (c) 2026 Pank.
Bundled: tweetnacl-js (public domain), IBM Plex Mono (SIL Open Font License 1.1).
C

SIZE=$(du -sk "$PKG" | cut -f1)
cat > "$PKG/DEBIAN/control" <<CTRL
Package: tonefer
Version: ${VERSION}
Section: net
Priority: optional
Architecture: all
Installed-Size: ${SIZE}
Depends: python3 (>= 3.10), python3-aiohttp, python3-nacl, python3-qrcode, python3-psutil, python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0
Recommends: network-manager
Maintainer: Pank <pankqx@gmail.com>
Homepage: https://github.com/pankqx/tonefer
Description: Private, offline transfer between your phone and your laptop
 Send notes, photos and files between an Android phone and this computer over
 the phone's hotspot, USB tethering or Wi-Fi. End-to-end encrypted, no cloud,
 no accounts. Includes a live transfer speedometer and hotspot auto-join.
CTRL

cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  # Start the background service at every login, for every user.
  systemctl --global enable tonefer.service >/dev/null 2>&1 || true
  # Let the phone reach the laptop if Ubuntu's firewall is on.
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow 8765/tcp comment tonefer >/dev/null 2>&1 || true
  fi
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi
exit 0
POST
cat > "$PKG/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  systemctl --global disable tonefer.service >/dev/null 2>&1 || true
fi
exit 0
PRE
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/prerm"

dpkg-deb --root-owner-group --build "$PKG" "$ROOT/dist/tonefer_${VERSION}_all.deb" >/dev/null
echo "$ROOT/dist/tonefer_${VERSION}_all.deb"
