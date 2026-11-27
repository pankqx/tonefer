"""Phone backup over USB: every photo and video on an Android phone, onto this laptop.

Uses adb (Android's own USB debugging tool), so it reaches every folder the phone keeps
pictures in: Camera, Screenshots, WhatsApp, Telegram, Instagram, Downloads, memory card...
No app on the phone is needed, just "USB debugging" switched on once.

Safety rules:
  * "Copy" never changes anything on the phone.
  * "Move" deletes a phone file only after the laptop copy has the same size AND the same
    MD5 checksum. A file that fails the check stays on the phone.
  * Each finished file is written down in <library>/.backup/state.db, so a stopped or
    interrupted backup continues where it left off and never copies a file twice.

Photos land in <library>/<year>/<year>-<month>/, which the Gallery shows by itself when the
library is inside ~/Tonefer (the default is ~/Tonefer/Phone backup).
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PHONE_ROOT = "/storage/emulated/0"
STATE_DIR = ".backup"
PRUNE = ["Android/data", "Android/obb"]   # app caches and game data, never your own photos

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif", ".dng", ".tif", ".tiff", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".3gp", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts"}
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AdbError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Dates and sources
# --------------------------------------------------------------------------- #
_DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d{3})")
_EPOCH_MS_RE = re.compile(r"(?<!\d)(1[3-9]\d{11})(?!\d)")


def date_for(name: str, mtime: float) -> datetime:
    """When a photo was taken. Camera and WhatsApp names carry the date (IMG_20231005_..,
    IMG-20231005-WA0001), Telegram/Snapchat use epoch milliseconds; otherwise the file time."""
    top = datetime.now().year + 1
    m = _DATE_RE.search(name)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        if 2000 <= y <= top:
            try:
                return datetime(y, mo, d)
            except ValueError:
                pass
    m = _EPOCH_MS_RE.search(name)
    if m:
        try:
            dt = datetime.fromtimestamp(int(m.group(1)) / 1000)
            if 2005 <= dt.year <= top:
                return dt
        except (OverflowError, OSError, ValueError):
            pass
    try:
        return datetime.fromtimestamp(mtime)
    except (OverflowError, OSError, ValueError):
        return datetime(1970, 1, 1)


_SOURCES = [
    ("/dcim/camera", "Camera"), ("screenshot", "Screenshots"), ("screen record", "Screen recordings"),
    ("screenrecord", "Screen recordings"), ("whatsapp", "WhatsApp"), ("telegram", "Telegram"),
    ("instagram", "Instagram"), ("snapchat", "Snapchat"), ("/download", "Downloads"), ("bluetooth", "Bluetooth"),
]
_GENERIC = {"sdcard", "storage", "emulated", "0", "self", "primary", "android", "media"}


def source_of(path: str) -> str:
    low = path.lower()
    for needle, label in _SOURCES:
        if needle in low:
            return label
    for p in reversed([p for p in path.split("/") if p][:-1]):
        if p.lower() not in _GENERIC and not re.fullmatch(r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}", p):
            return p
    return "Other"


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# --------------------------------------------------------------------------- #
# adb
# --------------------------------------------------------------------------- #
def find_adb() -> str | None:
    found = os.environ.get("TONEFER_ADB") or shutil.which("adb")
    if found:
        return found
    exe = "adb.exe" if sys.platform.startswith("win") else "adb"
    for base in (Path.home() / "Android" / "Sdk", Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk",
                 Path.home() / "platform-tools", Path("C:/platform-tools")):
        cand = base / "platform-tools" / exe if base.name == "Sdk" else base / exe
        if cand.is_file():
            return str(cand)
    return None


def q(path: str) -> str:
    return shlex.quote(path)


class Adb:
    def __init__(self, serial: str | None = None):
        self.adb = find_adb()
        if not self.adb:
            hint = ("Download Android platform-tools from developer.android.com/tools/releases/platform-tools "
                    "and unzip it to C:\\platform-tools." if sys.platform.startswith("win")
                    else "Install it with:  sudo apt install adb")
            raise AdbError("adb (Android's USB tool) isn't installed. " + hint)
        self.serial = serial

    def _cmd(self, *args: str) -> list[str]:
        return [self.adb] + (["-s", self.serial] if self.serial else []) + list(args)

    def _run(self, args: list[str], timeout: float) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(args, capture_output=True, text=True, errors="replace",
                                  timeout=timeout, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired as e:
            raise AdbError("The phone stopped answering. Unlock it and check the cable.") from e

    def shell(self, command: str, timeout: float = 600) -> str:
        return self._run(self._cmd("shell", command), timeout).stdout

    def pull(self, remotes: list[str], local_dir: str) -> subprocess.Popen:
        """adb pull -a REMOTE... DIR/  (-a keeps each file's date)."""
        return subprocess.Popen(self._cmd("pull", "-a", *remotes, local_dir.rstrip("/\\") + os.sep),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
                                creationflags=_NO_WINDOW)

    def devices(self) -> list[dict]:
        out = []
        for line in self._run([self.adb, "devices", "-l"], 20).stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2 or line.startswith("*"):
                continue
            model = next((p.split(":", 1)[1].replace("_", " ") for p in parts[2:] if p.startswith("model:")), "")
            serial = parts[0]
            out.append({"serial": serial, "state": parts[1], "model": model,
                        "wireless": ":" in serial or "_adb-tls-connect" in serial})
        return out

    def pick(self) -> dict:
        devs = self.devices()
        ready = [d for d in devs if d["state"] == "device"]
        if self.serial:
            ready = [d for d in ready if d["serial"] == self.serial]
        if not ready:
            if any(d["state"] == "unauthorized" for d in devs):
                raise AdbError("The phone is connected but hasn't allowed this laptop yet. "
                               "Unlock it and tap Allow on the 'Allow USB debugging?' message.")
            if devs:
                raise AdbError(f"The phone shows as {devs[0]['state']}. Unplug the cable and plug it in again.")
            raise AdbError("No phone found. Connect it with a USB cable and turn on USB debugging (steps below).")
        ready.sort(key=lambda d: d["wireless"])    # prefer the cable when both are there
        self.serial = ready[0]["serial"]
        return ready[0]

    def connect(self, address: str) -> str:
        r = self._run([self.adb, "connect", address], 30)
        return (r.stdout + r.stderr).strip()

    def pair(self, address: str, code: str) -> str:
        r = self._run([self.adb, "pair", address, code], 30)
        return (r.stdout + r.stderr).strip()


# --------------------------------------------------------------------------- #
# Scan
# --------------------------------------------------------------------------- #
@dataclass
class RemoteFile:
    path: str
    size: int
    mtime: int

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def kind(self) -> str:
        return "video" if os.path.splitext(self.name)[1].lower() in VIDEO_EXT else "photo"

    @property
    def source(self) -> str:
        return source_of(self.path)

    @property
    def taken(self) -> datetime:
        return date_for(self.name, self.mtime)


def storage_roots(adb: Adb) -> list[str]:
    roots = [PHONE_ROOT]
    for entry in adb.shell("ls /storage 2>/dev/null", timeout=20).split():
        if re.fullmatch(r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}", entry):   # memory card
            roots.append(f"/storage/{entry}")
    return roots


def _find_command(root: str, hidden: bool) -> str:
    prune = " -o ".join(f"-path {q(root + '/' + p)}" for p in PRUNE)
    if not hidden:
        prune += " -o \\( -type d -name '.*' \\)"
    exts = " -o ".join(f"-iname '*{e}'" for e in sorted(MEDIA_EXT))
    skip_hidden_files = "" if hidden else "! -name '.*' "
    return (f"find {q(root)} \\( {prune} \\) -prune -o -type f {skip_hidden_files}"
            f"\\( {exts} \\) -exec stat -c '%s|%Y|%n' {{}} + 2>/dev/null")


def scan(adb: Adb, hidden: bool = False, say=lambda m: None) -> list[RemoteFile]:
    files, seen = [], set()
    for root in storage_roots(adb):
        say("Memory card" if root != PHONE_ROOT else "Phone storage")
        for line in adb.shell(_find_command(root, hidden), timeout=1800).splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3 or not parts[0].isdigit() or parts[2] in seen:
                continue
            path = parts[2]
            if path.rsplit("/", 1)[-1].startswith((".trashed-", ".pending-")):
                continue   # already in the phone's own recycle bin
            seen.add(path)
            files.append(RemoteFile(path, int(parts[0]), int(parts[1] or 0)))
    files.sort(key=lambda f: f.path)
    return files


def summarize(files: list[RemoteFile], done: set[str]) -> dict:
    by: dict[str, dict] = defaultdict(lambda: {"files": 0, "bytes": 0, "photos": 0, "videos": 0, "saved": 0})
    for f in files:
        s = by[f.source]
        s["files"] += 1
        s["bytes"] += f.size
        s["photos" if f.kind == "photo" else "videos"] += 1
        s["saved"] += f.path in done
    return {
        "files": len(files), "bytes": sum(f.size for f in files),
        "photos": sum(f.kind == "photo" for f in files), "videos": sum(f.kind == "video" for f in files),
        "saved": sum(f.path in done for f in files),
        "sources": [{"name": k, **v} for k, v in sorted(by.items(), key=lambda kv: -kv[1]["bytes"])],
    }


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
class State:
    def __init__(self, library: Path):
        self.library = library
        self.dir = library / STATE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.dir / "state.db", check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS files (
            remote TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, source TEXT, kind TEXT, taken TEXT,
            dest TEXT, status TEXT, md5 TEXT, deleted INTEGER DEFAULT 0, error TEXT, updated TEXT)""")
        self.db.commit()

    def get(self, remote: str):
        with self.lock:
            return self.db.execute("SELECT size, dest, status, deleted FROM files WHERE remote=?", (remote,)).fetchone()

    def done(self) -> set[str]:
        with self.lock:
            return {r[0] for r in self.db.execute("SELECT remote FROM files WHERE status='done'")}

    def mark(self, f: RemoteFile, dest: str | None, status: str, md5: str | None = None, error: str | None = None):
        with self.lock:
            self.db.execute(
                """INSERT INTO files(remote,size,mtime,source,kind,taken,dest,status,md5,error,updated)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(remote) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
                     dest=COALESCE(excluded.dest, files.dest), status=excluded.status,
                     md5=COALESCE(excluded.md5, files.md5), error=excluded.error, updated=excluded.updated""",
                (f.path, f.size, f.mtime, f.source, f.kind, f.taken.isoformat(), dest, status, md5, error,
                 datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

    def set_deleted(self, remotes: list[str]):
        with self.lock:
            self.db.executemany("UPDATE files SET deleted=1 WHERE remote=?", [(r,) for r in remotes])
            self.db.commit()

    def export(self):
        """A plain list of what came from where, readable in any spreadsheet."""
        with self.lock:
            rows = self.db.execute("SELECT remote, dest, source, kind, taken, size, md5, deleted FROM files "
                                   "WHERE status='done' ORDER BY taken").fetchall()
        with open(self.dir / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["phone_path", "laptop_path", "from", "kind", "date", "bytes", "md5", "removed_from_phone"])
            w.writerows(rows)

    def close(self):
        with self.lock:
            self.db.close()


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while chunk := fh.read(4 << 20):
            h.update(chunk)
    return h.hexdigest()


def _chunks(items: list[str], limit: int = 6000):
    chunk, length = [], 0
    for it in items:
        if chunk and length + len(it) + 3 > limit:
            yield chunk
            chunk, length = [], 0
        chunk.append(it)
        length += len(it) + 3
    if chunk:
        yield chunk


# --------------------------------------------------------------------------- #
# Copy / move
# --------------------------------------------------------------------------- #
class Run:
    BATCH_FILES = 60
    BATCH_BYTES = 1 << 30

    def __init__(self, adb: Adb, library: Path, mode: str, verify: bool, stop: threading.Event, p: dict, log):
        assert mode in ("copy", "move")
        self.adb, self.library, self.mode, self.stop, self.p, self.log = adb, library, mode, stop, p, log
        self.verify = verify or mode == "move"       # moving always checks before deleting
        self.state = State(library)
        self.stage = library / STATE_DIR / "incoming"
        self.reserved: set[Path] = set()
        self.window: list[tuple[float, int]] = []

    # ---- phone side helpers ---- #
    def remote_md5(self, paths: list[str]) -> dict[str, str]:
        out = {}
        for chunk in _chunks(paths):
            for line in self.adb.shell("md5sum " + " ".join(q(p) for p in chunk), timeout=3600).splitlines():
                h, sep, p = line.partition("  ")
                if sep and len(h) == 32:
                    out[p] = h.lower()
        return out

    def delete_on_phone(self, paths: list[str]):
        if not paths:
            return
        for chunk in _chunks(paths):
            self.adb.shell("rm -f " + " ".join(q(p) for p in chunk))
            # Tell the phone's own gallery the files are gone (it would also notice on its next rescan).
            where = "_data IN (" + ",".join("'" + p.replace("'", "''") + "'" for p in chunk) + ")"
            self.adb.shell(f"content delete --uri content://media/external/file --where {q(where)}", timeout=120)
        still = set()
        for chunk in _chunks(paths):
            still.update(l.strip() for l in self.adb.shell("ls -d " + " ".join(q(p) for p in chunk) + " 2>/dev/null").splitlines())
        gone = [p for p in paths if p not in still]
        self.state.set_deleted(gone)
        self.p["removed"] += len(gone)

    # ---- laptop side helpers ---- #
    def folder(self, f: RemoteFile) -> Path:
        t = f.taken
        return self.library / f"{t:%Y}" / f"{t:%Y-%m}"

    def dest_for(self, f: RemoteFile, fresh: bool = False) -> tuple[Path, bool]:
        """Where a file goes, and whether a same-name, same-size file is already there."""
        folder, (stem, ext) = self.folder(f), os.path.splitext(f.name)
        cand, i = folder / f.name, 2
        while True:
            if cand not in self.reserved:
                if not cand.exists():
                    self.reserved.add(cand)
                    return cand, False
                if not fresh and cand.stat().st_size == f.size:
                    self.reserved.add(cand)
                    return cand, True
            cand, i = folder / f"{stem} ({i}){ext}", i + 1

    def tick(self, inflight: int = 0):
        now, total = time.monotonic(), self.p["done_bytes"] + inflight
        self.window.append((now, total))
        while len(self.window) > 2 and now - self.window[0][0] > 10:
            self.window.pop(0)
        t0, b0 = self.window[0]
        if now - t0 > 0.5:
            self.p["speed"] = (total - b0) / (now - t0)
        self.p["live_bytes"] = total

    def finish(self, f: RemoteFile, dest: Path, md5: str | None):
        self.state.mark(f, str(dest.relative_to(self.library)), "done", md5=md5)
        self.p["done_files"] += 1
        self.p["done_bytes"] += f.size

    def fail(self, f: RemoteFile, why: str):
        self.p["failed"].append({"path": f.path, "error": why})
        self.state.mark(f, None, "failed", error=why)

    # ---- main ---- #
    def run(self, files: list[RemoteFile]):
        p = self.p
        pull: list[tuple[RemoteFile, Path]] = []
        check: list[tuple[RemoteFile, Path]] = []    # already on the laptop: confirm (and delete when moving)
        for f in files:
            row = self.state.get(f.path)
            if row and row[2] == "done" and row[0] == f.size and row[1] and (self.library / row[1]).exists():
                if self.mode == "move" and not row[3]:
                    check.append((f, self.library / row[1]))
                else:
                    p["skipped"] += 1
                continue
            dest, exists = self.dest_for(f)
            (check if exists else pull).append((f, dest))

        if not self.verify:
            for f, dest in check:     # same name and size in the right month: already backed up
                self.state.mark(f, str(dest.relative_to(self.library)), "done")
                p["skipped"] += 1
            check = []

        p["total_files"] = len(pull) + len(check)
        p["total_bytes"] = sum(f.size for f, _ in pull + check)
        need = sum(f.size for f, _ in pull)
        free = shutil.disk_usage(self.library).free
        if need > free - (512 << 20):
            raise AdbError(f"Not enough space on the laptop: this needs {human(need)} but only {human(free)} is free. "
                           "Choose a folder on a bigger drive.")
        self.log(f"{len(pull)} files to copy ({human(need)}), {p['skipped']} already on the laptop")

        if check:
            p["current"] = "Checking files that are already on the laptop"
            remote = self.remote_md5([f.path for f, _ in check])
            ok = []
            for f, dest in check:
                if self.stop.is_set():
                    break
                local = md5_file(dest)
                if remote.get(f.path) == local:
                    self.finish(f, dest, local)
                    ok.append(f.path)
                else:                        # same name and size, different picture: keep both
                    pull.append((f, self.dest_for(f, fresh=True)[0]))
            if self.mode == "move":
                self.delete_on_phone(ok)

        retry = []
        for batch in self.batches(pull):
            if self.stop.is_set():
                break
            retry += self.pull_batch(batch, final=False)
        if retry and not self.stop.is_set():
            self.log(f"Trying {len(retry)} file(s) again, one at a time")
            for item in retry:
                if self.stop.is_set():
                    break
                self.pull_batch([item], final=True)

        shutil.rmtree(self.stage, ignore_errors=True)
        self.state.export()
        self.state.close()

    def batches(self, items):
        batch, names, size = [], set(), 0
        for f, dest in items:
            if batch and (len(batch) >= self.BATCH_FILES or size + f.size > self.BATCH_BYTES or f.name in names):
                yield batch
                batch, names, size = [], set(), 0
            batch.append((f, dest))
            names.add(f.name)
            size += f.size
        if batch:
            yield batch

    def pull_batch(self, batch, final: bool):
        """Pull into a staging folder, check each file, move it into place. Returns failures."""
        shutil.rmtree(self.stage, ignore_errors=True)
        self.stage.mkdir(parents=True, exist_ok=True)
        self.p["current"] = batch[0][0].path.replace(PHONE_ROOT + "/", "")
        proc = self.adb.pull([f.path for f, _ in batch], str(self.stage))
        while proc.poll() is None:
            if self.stop.is_set():
                proc.terminate()
                proc.wait()
                return []
            time.sleep(0.4)
            try:
                inflight = sum(e.stat().st_size for e in os.scandir(self.stage) if e.is_file())
            except OSError:
                inflight = 0
            self.tick(inflight)
        _, err = proc.communicate()
        errors = [l for l in (err or "").splitlines() if "error" in l.lower()]
        remote = self.remote_md5([f.path for f, _ in batch]) if self.verify else {}

        failed, moved = [], []
        for f, dest in batch:
            staged = self.stage / f.name
            if not staged.exists() or staged.stat().st_size != f.size:
                failed.append((f, dest))
                if final:
                    self.fail(f, next((l for l in errors if f.name in l), errors[-1] if errors else "copy incomplete"))
                continue
            md5 = md5_file(staged) if self.verify else None
            if self.verify and remote.get(f.path) != md5:
                failed.append((f, dest))
                if final:
                    self.fail(f, "checksum didn't match, so it was left on the phone")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, dest)
            try:
                os.utime(dest, (f.mtime, f.mtime))
            except OSError:
                pass
            self.finish(f, dest, md5)
            moved.append(f.path)
        if self.mode == "move" and moved:
            self.p["current"] = f"Freeing space: removing {len(moved)} checked file(s) from the phone"
            self.delete_on_phone(moved)
        self.tick()
        return failed


# --------------------------------------------------------------------------- #
# Controller used by the server (one job at a time, runs in a thread)
# --------------------------------------------------------------------------- #
class Backup:
    def __init__(self, config, default_library: Path, on_done=None):
        self.config = config
        self.default_library = default_library
        self.on_done = on_done            # called (in the worker thread) after a copy/move
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.device: dict | None = None
        self.files: list[RemoteFile] = []
        self.summary: dict | None = None
        self.hidden = False
        self.error = ""
        self.lines: list[str] = []
        self.p = self._fresh("idle")

    @property
    def library(self) -> Path:
        return Path(self.config.get("backup_dir") or self.default_library).expanduser()

    def set_library(self, path: str | None):
        self.config.set(backup_dir=path or None)
        self.summary = None

    @staticmethod
    def _fresh(phase: str, message: str = "") -> dict:
        return {"phase": phase, "message": message, "mode": "", "total_files": 0, "total_bytes": 0,
                "done_files": 0, "done_bytes": 0, "live_bytes": 0, "skipped": 0, "removed": 0,
                "speed": 0.0, "current": "", "started": 0.0, "failed": []}

    def log(self, msg: str):
        self.lines = (self.lines + [time.strftime("%H:%M  ") + msg])[-120:]

    @property
    def busy(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def status(self) -> dict:
        p = dict(self.p)
        p["failed_count"] = len(p["failed"])
        p["failed"] = p["failed"][-30:]
        left = p["total_bytes"] - p["live_bytes"]
        p["eta"] = left / p["speed"] if p["speed"] > 1 and left > 0 and p["phase"] == "running" else None
        return {"busy": self.busy, "adb": bool(find_adb()), "device": self.device, "error": self.error,
                "library": str(self.library), "default_library": str(self.default_library),
                "hidden": self.hidden, "summary": self.summary, "progress": p, "log": self.lines[-30:]}

    def refresh(self):
        if self.busy:
            return
        try:
            adb = Adb()
            self.device = adb.pick()
            self.error = ""
        except AdbError as e:
            self.device, self.error = None, str(e)

    def _start(self, job):
        with self.lock:
            if self.busy:
                raise AdbError("Already working. Wait for it to finish or press Stop.")
            self.stop.clear()
            self.error = ""

            def wrap():
                try:
                    job()
                except AdbError as e:
                    self.error = str(e)
                    self.p.update(phase="error", message=str(e))
                    self.log(str(e))
                except Exception as e:     # keep Tonefer running whatever happens
                    self.error = f"Something went wrong: {type(e).__name__}: {e}"
                    self.p.update(phase="error", message=self.error)
                    self.log(self.error)

            self.thread = threading.Thread(target=wrap, name="tonefer-backup", daemon=True)
            self.thread.start()

    def start_scan(self, hidden: bool):
        self.hidden = hidden

        def job():
            adb = Adb()
            self.device = adb.pick()
            self.p = self._fresh("scanning", "Looking through every folder on the phone")
            self.log("Scanning " + (self.device["model"] or self.device["serial"]))
            self.files = scan(adb, hidden, say=lambda m: self.p.update(message=f"Looking through {m}"))
            self.library.mkdir(parents=True, exist_ok=True)
            st = State(self.library)
            self.summary = summarize(self.files, st.done())
            st.close()
            self.p = self._fresh("ready")
            self.log(f"Found {self.summary['files']:,} photos and videos ({human(self.summary['bytes'])})")

        self._start(job)

    def start_run(self, mode: str, verify: bool):
        if not self.files:
            raise AdbError("Scan the phone first.")
        if mode not in ("copy", "move"):
            raise AdbError("Unknown mode.")

        def job():
            adb = Adb(self.device["serial"] if self.device else None)
            self.device = adb.pick()
            self.library.mkdir(parents=True, exist_ok=True)
            self.p = self._fresh("running")
            self.p.update(mode=mode, started=time.time())
            self.log(f"{'Moving' if mode == 'move' else 'Copying'} to {self.library}")
            Run(adb, self.library, mode, verify, self.stop, self.p, self.log).run(self.files)
            p = self.p
            p["current"] = ""
            if self.stop.is_set():
                p.update(phase="stopped", message="Stopped. Press the same button again to carry on where it stopped.")
            else:
                parts = [f"{p['done_files']:,} new on the laptop", f"{p['skipped']:,} were already there"]
                if mode == "move":
                    parts.append(f"{p['removed']:,} removed from the phone")
                if p["failed"]:
                    parts.append(f"{len(p['failed'])} couldn't be copied")
                p.update(phase="done", message="Done: " + ", ".join(parts) + ".")
            self.log(p["message"])
            st = State(self.library)
            self.summary = summarize(self.files, st.done())
            st.close()
            if self.on_done:
                self.on_done()

        self._start(job)

    def connect(self, address: str) -> str:
        msg = Adb().connect(address)
        self.log(msg)
        self.refresh()
        return msg

    def pair(self, address: str, code: str) -> str:
        msg = Adb().pair(address, code)
        self.log(msg)
        return msg
