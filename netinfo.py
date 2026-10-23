"""Network helpers: which address the phone should use, and what might block it.

The usual reasons a phone shows "site can't be reached":
  1. The QR code holds an old address (laptop switched networks after it was drawn).
  2. The laptop picked the wrong network card (ethernet, VPN, Docker...).
  3. A firewall on the laptop drops incoming connections (ufw on Ubuntu,
     Windows Defender Firewall when the network is marked "Public").
This module helps with all three.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys

import psutil

SKIP_PREFIXES = ("lo", "docker", "veth", "br-", "virbr", "vmnet", "vbox", "vethernet",
                 "tailscale", "tun", "tap", "wg", "zt", "utun", "ham", "npcap", "loopback",
                 "bluetooth", "isatap", "teredo")


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        flags = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                             creationflags=flags)
        return out.stdout or ""
    except Exception:
        return ""


def route_ip() -> str | None:
    """Address of the card that carries the default route (the hotspot, when on one).

    UDP connect() sends no packets; it only asks the OS which source address it
    would use. Works offline as long as a default route exists.
    """
    for target in ("10.255.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith(("127.", "0.")):
                return ip
        except OSError:
            pass
        finally:
            s.close()
    return None


def addresses() -> list[dict]:
    """[{ip, iface}] the phone could reach, best first."""
    found: list[dict] = []
    stats = psutil.net_if_stats()
    for iface, addrs in psutil.net_if_addrs().items():
        st = stats.get(iface)
        if st and not st.isup:
            continue
        if iface.lower().startswith(SKIP_PREFIXES):
            continue
        for a in addrs:
            if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254.")):
                found.append({"ip": a.address, "iface": iface})

    best = route_ip()

    def rank(d: dict) -> tuple:
        ip, name = d["ip"], d["iface"].lower()
        wifi = name.startswith(("wl", "wi-fi", "wifi", "wlan")) or "wireless" in name
        private = ip.startswith(("192.168.", "10.")) or (
            ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)
        return (ip != best, not wifi, not private, ip)

    seen, out = set(), []
    for d in sorted(found, key=rank):
        if d["ip"] not in seen:
            seen.add(d["ip"])
            out.append(d)
    return out


def wifi_name() -> str | None:
    """SSID the laptop is on, so the UI can say 'connected to Pank's phone'."""
    if sys.platform.startswith("linux") and shutil.which("nmcli"):
        for line in _run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"]).splitlines():
            if line.startswith("yes:"):
                return line[4:].replace("\\:", ":") or None
    elif sys.platform.startswith("win"):
        for line in _run(["netsh", "wlan", "show", "interfaces"]).splitlines():
            k, _, v = line.partition(":")
            if k.strip().lower() == "ssid":
                return v.strip() or None
    elif sys.platform == "darwin":
        out = _run(["/usr/sbin/networksetup", "-getairportnetwork", "en0"])
        if ":" in out:
            return out.split(":", 1)[1].strip() or None
    return None


def firewall_hint(port: int) -> dict | None:
    """Best-effort detection of a firewall that would block the phone."""
    if sys.platform.startswith("linux"):
        if shutil.which("systemctl"):
            if _run(["systemctl", "is-active", "ufw"]).strip() == "active":
                return {"name": "ufw",
                        "text": "Ubuntu's firewall (ufw) is on and may block your phone.",
                        "fix": f"sudo ufw allow {port}/tcp"}
            if _run(["systemctl", "is-active", "firewalld"]).strip() == "active":
                return {"name": "firewalld",
                        "text": "firewalld is on and may block your phone.",
                        "fix": f"sudo firewall-cmd --add-port={port}/tcp"}
        return None
    if sys.platform.startswith("win"):
        out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-NetConnectionProfile | Where-Object {$_.IPv4Connectivity -ne 'Disconnected'}).NetworkCategory"],
                   timeout=4)
        if "Public" in out:
            return {"name": "windows-public",
                    "text": "Windows treats this network as Public, which blocks your phone.",
                    "fix": "Settings → Network & internet → Wi-Fi → (your hotspot) → set to Private network"}
        return {"name": "windows",
                "text": "If Windows asked about Python, it must be allowed on Private networks.",
                "fix": "Windows Security → Firewall → Allow an app → tick Python (Private)"}
    return None


def doctor(port: int) -> None:
    print("\n  tonefer doctor\n")
    ssid = wifi_name()
    print(f"  wi-fi        {ssid or 'not on wi-fi (turn on the phone hotspot and join it)'}")
    print(f"  route via    {route_ip() or 'no route'}")
    addrs = addresses()
    if not addrs:
        print("  addresses    none — the laptop is not on any network")
    for i, d in enumerate(addrs):
        tag = "  ← QR uses this" if i == 0 else ""
        print(f"  address      http://{d['ip']}:{port}   ({d['iface']}){tag}")
    fw = firewall_hint(port)
    if fw:
        print(f"\n  firewall     {fw['text']}\n  fix          {fw['fix']}")
    else:
        print("  firewall     nothing blocking found")
    print("\n  If the phone still can't open the page, type the address above into")
    print("  Chrome on the phone. If that fails too, it is the firewall.\n")


# --------------------------------------------------------------------------- #
# Hotspot auto-join: when the phone's hotspot appears, connect to it.
# --------------------------------------------------------------------------- #
def saved_wifi() -> list[str]:
    """Wi-Fi networks this laptop already knows (has joined before)."""
    names: list[str] = []
    if sys.platform.startswith("linux") and shutil.which("nmcli"):
        for line in _run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"]).splitlines():
            name, _, kind = line.rpartition(":")
            if kind == "802-11-wireless" and name:
                names.append(name.replace("\\:", ":"))
    elif sys.platform.startswith("win"):
        for line in _run(["netsh", "wlan", "show", "profiles"]).splitlines():
            if ":" in line and "profile" in line.lower():
                n = line.split(":", 1)[1].strip()
                if n:
                    names.append(n)
    return sorted(dict.fromkeys(names), key=str.lower)


def visible_wifi(rescan: bool = False) -> set[str]:
    """SSIDs currently in range."""
    found: set[str] = set()
    if sys.platform.startswith("linux") and shutil.which("nmcli"):
        if rescan:
            _run(["nmcli", "device", "wifi", "rescan"], timeout=6)
        for line in _run(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "no"], timeout=6).splitlines():
            s = line.replace("\\:", ":").strip()
            if s:
                found.add(s)
    elif sys.platform.startswith("win"):
        for line in _run(["netsh", "wlan", "show", "networks"], timeout=6).splitlines():
            k, _, v = line.partition(":")
            if k.strip().upper().startswith("SSID") and v.strip():
                found.add(v.strip())
    return found


def join_wifi(name: str) -> bool:
    """Connects to a known Wi-Fi network. Returns True on success."""
    if sys.platform.startswith("linux") and shutil.which("nmcli"):
        out = _run(["nmcli", "connection", "up", "id", name], timeout=30)
        if "successfully" in out.lower():
            return True
        out = _run(["nmcli", "device", "wifi", "connect", name], timeout=30)
        return "successfully" in out.lower()
    if sys.platform.startswith("win"):
        out = _run(["netsh", "wlan", "connect", f"name={name}"], timeout=15)
        return "success" in out.lower()
    return False
