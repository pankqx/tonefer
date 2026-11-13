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
# Updates on Ubuntu go here, in your own home folder, so they never need your password.
# /opt/tonefer/server.py hands over to the newest copy found here when it starts.
USER_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "tonefer"
CURRENT = USER_DIR / "current"
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
    if sys.platform.startswith("linux") and (HERE == Path("/opt/tonefer") or USER_DIR in HERE.parents):
        return "user"
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


def install_user(deb: Path, version: str) -> tuple[bool, str]:
    """Unpacks the new version into ~/.local/share/tonefer and makes it current. No password:
    nothing outside your home folder changes. Checked before it's switched on."""
    versions = USER_DIR / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    stage = versions / f".{version}.unpack"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    try:
        if shutil.which("dpkg-deb"):
            r = subprocess.run(["dpkg-deb", "-x", str(deb), str(stage)], capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                return False, f"Couldn't unpack the update: {(r.stderr or '').strip()[:200]}"
        else:
            _unpack_deb(deb, stage)
        app = stage / "opt" / "tonefer"
        if not (app / "server.py").exists():
            return False, "The downloaded update looks damaged. Try again."
        # The new version must start on this computer's Python and libraries before we switch.
        test = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import server, PIL.Image", str(app)],
                              capture_output=True, text=True, timeout=60, cwd=str(app))
        if test.returncode != 0:
            missing = (test.stderr or test.stdout).strip().splitlines()[-1:] or ["unknown error"]
            return False, f"This update needs a full install ({missing[0]}). Download tonefer.deb from GitHub and open it."
        dest = versions / version
        shutil.rmtree(dest, ignore_errors=True)
        os.replace(app, dest)
        link = USER_DIR / ".current.new"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(dest)
        os.replace(link, CURRENT)
        # Keep this version and the one before it; remove older copies.
        keep = {dest.name, HERE.name}
        for old in sorted(versions.iterdir()):
            if old.is_dir() and old.name not in keep and not old.name.startswith("."):
                shutil.rmtree(old, ignore_errors=True)
        return True, "Installed"
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _unpack_deb(deb: Path, dest: Path) -> None:
    """A .deb is an ar archive holding data.tar.*: read it without dpkg."""
    import io
    import tarfile
    with open(deb, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            raise OSError("not a .deb file")
        while header := f.read(60):
            name = header[:16].decode().strip().rstrip("/")
            size = int(header[48:58].decode().strip())
            data = f.read(size)
            if size % 2:
                f.read(1)
            if name.startswith("data.tar"):
                with tarfile.open(fileobj=io.BytesIO(data)) as t:
                    t.extractall(dest, filter="data")
                return
    raise OSError("no data in the .deb")


def newest_copy(here: Path, version: str) -> Path | None:
    """The server.py of a newer Tonefer installed by the updater, if there is one."""
    if os.environ.get("TONEFER_NO_HANDOVER") or not sys.platform.startswith("linux"):
        return None
    try:
        target = (CURRENT / "server.py").resolve(strict=True)
        if target.parent == here:
            return None
        if parse((target.parent / "VERSION").read_text()) > parse(version):
            return target
    except (OSError, ValueError):
        return None
    return None


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
