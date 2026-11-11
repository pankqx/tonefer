"""Big transfers for Tonefer: chunked, end-to-end encrypted, constant memory, and folders as zip.

Protocol v2 (docs/PROTOCOL.md):

* A file moves as a series of chunks. Each chunk is sealed on its own:
      secretbox( header || data ),  header = tid (16 ASCII) | index (uint32 BE) | flags (uint8, 1 = last)
  The header ties every chunk to its transfer and position, so chunks can't be swapped,
  replayed into another transfer or cut short without the receiver noticing.
* Uploads (phone -> laptop) are one small POST per chunk, so they work from any browser and
  can be retried after a dropped connection. Downloads (laptop -> phone) are one streamed
  response of length-prefixed sealed frames.
* Several files can be sent "into" a zip: the laptop writes them straight into one archive as
  they arrive (ZIP64, no size limit), and publishes the archive when the phone says it's done.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import struct
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Callable

CHUNK = 4 * 1024 * 1024    # plaintext bytes per uploaded chunk
DCHUNK = 1024 * 1024       # plaintext bytes per downloaded frame
HDR = struct.Struct(">16sIB")
LAST = 1
SEAL_OVERHEAD = 24 + 16    # nonce + Poly1305 tag
FRAME_OVERHEAD = 4 + SEAL_OVERHEAD + HDR.size
STALE_SECONDS = 30 * 60    # unfinished transfers are dropped after 30 minutes of silence
ZIP64_SAFE = 0xFFFFFFFF - (64 << 20)

# Already-compressed formats are stored as they are; everything else gets fast deflate.
STORED_EXT = {
    "jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "avif", "jxl",
    "mp4", "mov", "m4v", "mkv", "webm", "avi", "3gp", "mp3", "m4a", "aac", "ogg", "opus", "flac",
    "zip", "7z", "rar", "gz", "tgz", "bz2", "xz", "zst", "apk", "aab", "jar", "docx", "xlsx",
    "pptx", "odt", "ods", "odp", "epub", "pdf", "dmg", "iso",
}


class TransferError(Exception):
    def __init__(self, status: int, text: str, **extra):
        super().__init__(text)
        self.status, self.text, self.extra = status, text, extra


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def header(tid: str, index: int, last: bool) -> bytes:
    return HDR.pack(tid.encode("ascii")[:16].ljust(16, b"0"), index, LAST if last else 0)


def parse(plain: bytes) -> tuple[str, int, bool, memoryview]:
    if len(plain) < HDR.size:
        raise TransferError(400, "Chunk too short")
    tid, index, flags = HDR.unpack_from(plain)
    return tid.decode("ascii", "replace"), index, bool(flags & LAST), memoryview(plain)[HDR.size:]


def frames_size(size: int, start: int = 0) -> int:
    """Exact byte length of a v2 download of a `size`-byte file, starting at frame `start`."""
    frames = max(1, -(-size // DCHUNK))
    remaining = max(size - start * DCHUNK, 0)
    return remaining + max(frames - start, 0) * FRAME_OVERHEAD


def stored(name: str) -> bool:
    return name.rsplit(".", 1)[-1].lower() in STORED_EXT if "." in name else False


def clean_part(part: str) -> str:
    bad = '<>:"\\|?*\x00'
    part = "".join("_" if c in bad or ord(c) < 32 else c for c in part).strip().rstrip(".")
    return part[:150] or "_"


def clean_path(path: str) -> str:
    """A relative path that is safe inside a zip and on any file system: no '..', no drive letters."""
    parts = [p for p in str(path).replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return "/".join(clean_part(p) for p in parts) or "file"


def zip_name(name: str) -> str:
    name = clean_part(Path(str(name).replace("\\", "/")).name or "Tonefer")
    return name if name.lower().endswith(".zip") else name + ".zip"


def _zip_info(arcname: str, size: int, mtime: float | None) -> zipfile.ZipInfo:
    t = time.localtime(mtime if mtime and mtime > 315532800 else time.time())  # zip dates start in 1980
    zi = zipfile.ZipInfo(arcname, date_time=t[:6])
    zi.compress_type = zipfile.ZIP_STORED if stored(arcname) else zipfile.ZIP_DEFLATED
    zi.file_size = max(size, 0)
    zi.external_attr = 0o644 << 16
    for attr in ("compress_level", "_compresslevel"):  # name changed in Python 3.13
        try:
            setattr(zi, attr, 1)
        except AttributeError:
            pass
    return zi


class ZipBuild:
    """One zip archive being filled, entry by entry, as files arrive."""

    def __init__(self, zid: str, name: str, origin: str, folder: Path, files: int = 0, size: int = -1):
        self.id, self.name, self.origin = zid, zip_name(name), origin
        self.expected_files, self.expected_size = files, size
        self.tmp = folder / f"{zid}.zip.part"
        self.zf = zipfile.ZipFile(self.tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True)
        self.entry = None
        self.owner: str | None = None     # transfer id currently writing an entry
        self.count = 0
        self.bytes = 0
        self.used: set[str] = set()
        self.lock = asyncio.Lock()
        self.last_seen = time.monotonic()
        self.meter = None
        self.item: str | None = None    # history id once published

    def _unique(self, arc: str) -> str:
        if arc not in self.used:
            self.used.add(arc)
            return arc
        stem, dot, ext = arc.rpartition(".")
        if not dot or "/" in ext:
            stem, ext = arc, ""
        n = 1
        while True:
            cand = f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})"
            if cand not in self.used:
                self.used.add(cand)
                return cand
            n += 1

    def open_entry(self, path: str, size: int, mtime: float | None):
        arc = self._unique(clean_path(path))
        zi = _zip_info(arc, size, mtime)
        self.entry = self.zf.open(zi, "w", force_zip64=size < 0 or size > ZIP64_SAFE)
        return self.entry

    def write(self, data) -> None:
        self.entry.write(data)
        self.bytes += len(data)

    def close_entry(self) -> None:
        if self.entry is not None:
            self.entry.close()
            self.entry = None
            self.count += 1
        self.owner = None

    def finish(self) -> Path:
        self.close_entry()
        self.zf.close()
        return self.tmp

    def abort(self) -> None:
        try:
            if self.entry is not None:
                self.entry.close()
            self.zf.close()
        except Exception:
            pass
        self.zf = None
        self.tmp.unlink(missing_ok=True)


class Incoming:
    """One file arriving chunk by chunk, either into its own file or into a zip."""

    def __init__(self, tid: str, name: str, mime: str, size: int, origin: str,
                 tmp: Path | None = None, zipb: ZipBuild | None = None):
        self.id, self.name, self.mime, self.size, self.origin = tid, name, mime, size, origin
        self.tmp, self.zip = tmp, zipb
        self.fh = None
        self.next = 0
        self.bytes = 0
        self.done = False
        self.lock = asyncio.Lock()
        self.last_seen = time.monotonic()
        self.meter = None

    def write(self, data) -> None:
        if self.zip is not None:
            self.zip.write(data)
        else:
            self.fh.write(data)
        self.bytes += len(data)

    def close(self) -> None:
        if self.zip is not None:
            self.zip.close_entry()
        elif self.fh is not None:
            self.fh.close()
            self.fh = None

    def abort(self) -> None:
        try:
            if self.fh is not None:
                self.fh.close()
        except Exception:
            pass
        if self.tmp is not None:
            self.tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Laptop-side helpers
# --------------------------------------------------------------------------- #
def walk_folder(src: Path) -> list[Path]:
    files: list[Path] = []
    for root, dirs, names in os.walk(src, followlinks=False):
        dirs.sort()
        for n in sorted(names):
            p = Path(root) / n
            if p.is_symlink() or not p.is_file():
                continue
            files.append(p)
    return files


def zip_folder(src: Path, dest: Path, progress: Callable[[int, int, int], None]) -> tuple[int, int]:
    """Zips a folder from disk (the folder itself is the top-level entry). Returns (files, bytes)."""
    files = walk_folder(src)
    total = sum(p.stat().st_size for p in files)
    done = 0
    used: set[str] = set()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for i, p in enumerate(files):
            arc = clean_path(f"{src.name}/{p.relative_to(src).as_posix()}")
            if arc in used:
                continue
            used.add(arc)
            st = p.stat()
            zi = _zip_info(arc, st.st_size, st.st_mtime)
            with open(p, "rb") as fh, zf.open(zi, "w", force_zip64=st.st_size > ZIP64_SAFE) as w:
                while buf := fh.read(1 << 20):
                    w.write(buf)
                    done += len(buf)
                    progress(done, total, i)
        progress(done, total, len(files))
    return len(files), total


def unique_dir(base: Path) -> Path:
    p, n = base, 1
    while p.exists():
        p = base.with_name(f"{base.name} ({n})")
        n += 1
    return p


def extract_zip(zpath: Path) -> Path:
    """Unpacks next to the archive. Never writes outside the target folder, skips links."""
    with zipfile.ZipFile(zpath) as zf:
        infos = [zi for zi in zf.infolist() if (zi.external_attr >> 16) & 0o170000 != 0o120000]
        names = [[p for p in zi.filename.replace("\\", "/").split("/") if p not in ("", ".", "..")] for zi in infos]
        tops = {n[0] for n in names if n}
        # "Photos.zip" holding "Photos/…" unpacks to "Photos", not "Photos/Photos".
        single_top = len(tops) == 1 and all(len(n) > 1 or zi.is_dir() for zi, n in zip(infos, names) if n)
        if single_top:
            target = unique_dir(zpath.parent / clean_part(next(iter(tops))))
            names = [n[1:] for n in names]
        else:
            target = unique_dir(zpath.parent / clean_part(zpath.stem))
        target.mkdir(parents=True)
        root = target.resolve()
        for zi, parts in zip(infos, names):
            if not parts:
                continue
            out = target.joinpath(*[clean_part(p) for p in parts])
            if root not in out.resolve().parents and out.resolve() != root:
                continue
            if zi.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(zi) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            try:
                ts = time.mktime(zi.date_time + (0, 0, -1))
                os.utime(out, (ts, ts))
            except (OverflowError, ValueError, OSError):
                pass
    return target


def pick_folder(title: str = "Choose a folder to send to your phone") -> str | None:
    """Opens the system's folder picker. Returns a path, "" when cancelled, None if no picker exists."""
    home = str(Path.home())
    try:
        if sys.platform.startswith("win"):
            ps = (
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
                f"$f.Description='{title}';$f.ShowNewFolderButton=$false;"
                "$o=New-Object System.Windows.Forms.Form -Property @{TopMost=$true;ShowInTaskbar=$false};"
                "if($f.ShowDialog($o) -eq 'OK'){$f.SelectedPath}"
            )
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=3600)
            return r.stdout.decode("utf-8", "replace").strip()
        if sys.platform == "darwin":
            r = subprocess.run(["osascript", "-e", f'POSIX path of (choose folder with prompt "{title}")'],
                               capture_output=True, text=True, timeout=3600)
            return r.stdout.strip()
        if shutil.which("zenity"):
            r = subprocess.run(["zenity", "--file-selection", "--directory", f"--title={title}", f"--filename={home}/"],
                               capture_output=True, text=True, timeout=3600)
            return r.stdout.strip()
        if shutil.which("kdialog"):
            r = subprocess.run(["kdialog", "--getexistingdirectory", home, "--title", title],
                               capture_output=True, text=True, timeout=3600)
            return r.stdout.strip()
        if shutil.which("yad"):
            r = subprocess.run(["yad", "--file", "--directory", f"--title={title}"], capture_output=True, text=True, timeout=3600)
            return r.stdout.strip().rstrip("|")
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title=title, initialdir=home, mustexist=True)
        root.destroy()
        return path or ""
    except Exception:
        return None
