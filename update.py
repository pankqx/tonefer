"""One-click updates for the laptop app.

Checking and downloading need internet (the only part of Tonefer that does). Nothing about you
or your transfers is sent: it is a plain download of the public release from GitHub.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

REPO = "pankqx/tonefer"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/main/VERSION"
DEB_URL = f"https://github.com/{REPO}/releases/latest/download/tonefer.deb"
EXE_URL = f"https://github.com/{REPO}/releases/latest/download/ToneferSetup.exe"
HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "Tonefer-updater"}


def parse(v: str) -> tuple[int, ...]:
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


def newer(latest: str | None, current: str) -> bool:
    return bool(latest) and parse(latest) > parse(current)


def latest_version(timeout: float = 8) -> str | None:
    """The newest published release, or None when offline."""
    try:
        with urllib.request.urlopen(urllib.request.Request(API_URL, headers=UA), timeout=timeout) as r:
            tag = json.load(r).get("tag_name") or ""
            if tag:
                return tag.lstrip("vV")
    except Exception:
        pass
    try:
        with urllib.request.urlopen(urllib.request.Request(RAW_URL, headers=UA), timeout=timeout) as r:
            return r.read(40).decode("ascii", "replace").strip() or None
    except Exception:
        return None


def kind() -> str:
    """How this copy was installed, which decides how it can update itself."""
    if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
        return "windows"
    if HERE == Path("/opt/tonefer"):
        return "deb"
    if (HERE / ".git").exists() and shutil.which("git"):
        return "git"
    return "manual"


def download(url: str, dest: Path, progress: Callable[[int, int], None]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            done += len(chunk)
            if time.monotonic() - last > 0.2:
                last = time.monotonic()
                progress(done, total)
        progress(done, total)
    if done < 100_000:
        tmp.unlink(missing_ok=True)
        raise OSError("the download was incomplete")
    os.replace(tmp, dest)


def install_deb(path: Path) -> tuple[bool, str]:
    """Installs over the current version. Ubuntu asks for your password in its own dialog."""
    if not shutil.which("pkexec"):
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, str(path)])
            return False, "Opened the installer. Press Install there, then reopen Tonefer."
        return False, f"Downloaded to {path}. Install it with: sudo apt install {path}"
    r = subprocess.run(["pkexec", "apt-get", "install", "-y", "--allow-downgrades", str(path)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode in (126, 127):
        return False, "Update cancelled: the password dialog was closed."
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["unknown error"]
        return False, f"The installer failed: {tail[0]}"
    return True, "Installed"


def git_pull() -> tuple[bool, str]:
    r = subprocess.run(["git", "-C", str(HERE), "pull", "--ff-only"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["unknown error"]
        return False, f"git pull failed: {tail[0]}"
    return True, "Updated"


def run_windows_installer(path: Path) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path), "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART", "/RELAUNCH=1"], creationflags=flags, close_fds=True)


def restart() -> None:
    """Starts the new version in place of this one."""
    if shutil.which("systemctl"):
        active = subprocess.run(["systemctl", "--user", "is-active", "tonefer.service"], capture_output=True, text=True)
        if active.stdout.strip() == "active" and os.environ.get("INVOCATION_ID"):
            subprocess.Popen(["systemctl", "--user", "restart", "tonefer.service"])
            return
    os.execv(sys.executable, [sys.executable] + sys.argv)
