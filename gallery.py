"""The Gallery: every photo, video and file in the folders you choose, newest first.

Everything stays on this computer. The index lives in memory, thumbnails are cached in
~/.tonefer/thumbs, and "delete" always means the system Trash, so it can be undone.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

PHOTO = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "avif", "svg"}
VIDEO = {"mp4", "webm", "mov", "m4v", "mkv", "ogv", "3gp"}
FILE = {
    "pdf", "doc", "docx", "odt", "rtf", "txt", "md", "xls", "xlsx", "ods", "csv", "ppt", "pptx", "odp",
    "zip", "rar", "7z", "tar", "gz", "apk", "deb", "exe", "iso", "epub",
    "mp3", "wav", "m4a", "flac", "ogg", "opus", "aac", "json", "xml", "html", "py", "js", "java", "kt", "c", "cpp",
    "heic", "heif", "psd", "ai", "fig", "tex",
}
SKIP_DIRS = {
    "node_modules", "__pycache__", "venv", ".venv", "env", "site-packages", "build", "dist", "target", "snap",
    "AppData", "Application Data", "Library", "partial", "thumbs", "Trash", "$RECYCLE.BIN", "System Volume Information",
}
THUMB = 360


def default_roots() -> list[Path]:
    home = Path.home()
    names = ["Pictures", "Videos", "Downloads", "Desktop", "Documents", "Tonefer", "DCIM", "Screenshots"]
    roots = [home / n for n in names]
    one = home / "OneDrive"   # Windows often moves the user folders here
    roots += [one / n for n in ("Pictures", "Desktop", "Documents")]
    return [r for r in roots if r.is_dir()]


def kind_of(name: str) -> str | None:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in PHOTO:
        return "photo"
    if ext in VIDEO:
        return "video"
    if ext in FILE:
        return "file"
    return None


class Entry:
    __slots__ = ("id", "path", "name", "t", "m", "size", "kind")

    def __init__(self, path: str, name: str, mtime: float, size: int, kind: str):
        self.id = hashlib.sha1(path.encode("utf-8", "surrogatepass")).hexdigest()[:16]
        self.path, self.name, self.size, self.kind = path, name, size, kind
        self.m = mtime     # last modified: decides when the thumbnail must be remade
        self.t = mtime     # when it was taken: replaced by the photo's own date once read

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "t": int(self.t * 1000), "size": self.size, "kind": self.kind,
                "dir": os.path.dirname(self.path)}


# ---- "when was this taken?" ------------------------------------------------ #
_NAME_DATE = re.compile(r"(?<!\d)(20\d{2}|19\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?([0-2]\d|3[01])"
                        r"(?:[-_ .T]?([01]\d|2[0-3])[-_.:]?([0-5]\d)[-_.:]?([0-5]\d))?(?!\d)")
_MP4 = {"mp4", "mov", "m4v", "3gp"}


def _plausible(t: float) -> bool:
    return 631152000 < t < time.time() + 86400 * 2   # 1990 .. now


def exif_date(path: str) -> float | None:
    """DateTimeOriginal from a photo's EXIF block. Only the header is read."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif()
            raw = None
            try:
                raw = ex.get_ifd(0x8769).get(36867) or ex.get_ifd(0x8769).get(36868)
            except Exception:
                pass
            raw = raw or ex.get(306)
        if not raw:
            return None
        t = time.mktime(time.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S"))
        return t if _plausible(t) else None
    except Exception:
        return None


def mp4_date(path: str) -> float | None:
    """Creation time stored in an MP4/MOV header (the 'mvhd' box). Reads a few hundred bytes."""
    try:
        with open(path, "rb") as f:
            end = os.fstat(f.fileno()).st_size
            pos, stop = 0, end
            for _ in range(2000):
                if pos + 8 > stop:
                    return None
                f.seek(pos)
                size, kind = struct.unpack(">I4s", f.read(8))
                head = 8
                if size == 1:
                    size = struct.unpack(">Q", f.read(8))[0]
                    head = 16
                elif size == 0:
                    size = stop - pos
                if size < head:
                    return None
                if kind == b"moov":
                    pos, stop = pos + head, pos + size   # step inside
                    continue
                if kind == b"mvhd":
                    version = f.read(1)[0]
                    f.read(3)
                    secs = struct.unpack(">Q", f.read(8))[0] if version == 1 else struct.unpack(">I", f.read(4))[0]
                    t = secs - 2082844800   # seconds from 1904 to 1970
                    return float(t) if _plausible(t) else None
                pos += size
    except Exception:
        return None
    return None


def name_date(name: str) -> float | None:
    """Phones put the date in the file name: IMG_20241005_143022.jpg, Screenshot_2024-10-05-14-30-22.png…"""
    m = _NAME_DATE.search(name)
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.groups()
    try:
        t = time.mktime((int(y), int(mo), int(d), int(hh or 12), int(mm or 0), int(ss or 0), 0, 0, -1))
    except (OverflowError, ValueError):
        return None
    return t if _plausible(t) else None


def taken(e: "Entry") -> float | None:
    ext = e.name.rsplit(".", 1)[-1].lower()
    t = None
    if e.kind == "photo" and ext in ("jpg", "jpeg", "webp", "png", "tif", "tiff", "heic", "heif", "avif"):
        t = exif_date(e.path)
    elif e.kind == "video" and ext in _MP4:
        t = mp4_date(e.path)
    if t is None and e.kind != "file":
        t = name_date(e.name)
    return t


class Gallery:
    def __init__(self, app_dir: Path, config):
        self.config = config
        self.thumbs = app_dir / "thumbs"
        self.thumbs.mkdir(parents=True, exist_ok=True)
        self.entries: list[Entry] = []
        self.by_id: dict[str, Entry] = {}
        self.scanning = False
        self.scanned_at = 0.0
        self.progress: dict = {"phase": "idle"}
        self.recent: list[str] = []          # names seen just now, for the scanning animation
        self.dates_file = app_dir / "gallery-dates.json"
        self.dates: dict[str, list] = {}     # path -> [mtime, size, taken or 0]
        try:
            self.dates = json.loads(self.dates_file.read_text("utf-8"))
        except (OSError, ValueError):
            self.dates = {}
        self.lock = threading.Lock()
        self.ffmpeg = shutil.which("ffmpeg")

    # ---- folders ---------------------------------------------------------- #
    def roots(self) -> list[Path]:
        extra = [Path(p) for p in self.config.get("gallery_dirs", []) or []]
        hidden = set(self.config.get("gallery_hidden", []) or [])
        seen, out = set(), []
        for r in default_roots() + extra:
            key = str(r)
            if key in seen or key in hidden or not r.is_dir():
                continue
            seen.add(key)
            out.append(r)
        # A folder inside another chosen folder is already covered.
        return [r for r in out if not any(o != r and o in r.parents for o in out)]

    def folder_list(self) -> list[dict]:
        defaults = {str(p) for p in default_roots()}
        return [{"path": str(r), "default": str(r) in defaults} for r in self.roots()]

    def add_folder(self, path: str) -> None:
        dirs = list(self.config.get("gallery_dirs", []) or [])
        hidden = [h for h in (self.config.get("gallery_hidden", []) or []) if h != path]
        if path not in dirs:
            dirs.append(path)
        self.config.set(gallery_dirs=dirs, gallery_hidden=hidden)

    def remove_folder(self, path: str) -> None:
        dirs = [d for d in (self.config.get("gallery_dirs", []) or []) if d != path]
        hidden = list(self.config.get("gallery_hidden", []) or [])
        if path in {str(p) for p in default_roots()} and path not in hidden:
            hidden.append(path)
        self.config.set(gallery_dirs=dirs, gallery_hidden=hidden)

    # ---- scanning --------------------------------------------------------- #
    def _publish(self, found: list[Entry]) -> None:
        ordered = sorted(found, key=lambda x: x.t, reverse=True)
        with self.lock:
            self.entries = ordered
            self.by_id = {e.id: e for e in ordered}
            self.scanned_at = time.time()

    def _seen(self, text: str) -> None:
        self.recent.append(text)
        if len(self.recent) > 14:
            del self.recent[:-14]

    def scan(self) -> None:
        """Two passes. First a quick walk (one stat per file) so the grid fills at once, then the
        date each photo and video was taken is read and remembered, so later scans are instant."""
        if self.scanning:
            return
        self.scanning = True
        try:
            found: list[Entry] = []
            stack = [str(r) for r in self.roots()]
            last = time.monotonic()
            self.progress = {"phase": "walk", "found": 0, "dir": ""}
            while stack:
                d = stack.pop()
                self.progress = {"phase": "walk", "found": len(found), "dir": d}
                try:
                    with os.scandir(d) as it:
                        for e in it:
                            name = e.name
                            if name.startswith("."):
                                continue
                            try:
                                if e.is_dir(follow_symlinks=False):
                                    if name not in SKIP_DIRS:
                                        stack.append(e.path)
                                    continue
                                kind = kind_of(name)
                                if kind is None or not e.is_file(follow_symlinks=False):
                                    continue
                                st = e.stat(follow_symlinks=False)
                                if st.st_size == 0:
                                    continue
                                entry = Entry(e.path, name, st.st_mtime, st.st_size, kind)
                                known = self.dates.get(e.path)
                                if known and known[0] == int(st.st_mtime) and known[1] == st.st_size and known[2]:
                                    entry.t = known[2]
                                found.append(entry)
                                if len(found) % 37 == 0:
                                    self._seen(name)
                            except OSError:
                                continue
                except OSError:
                    continue
                if time.monotonic() - last > 1.5 and not self.entries:
                    last = time.monotonic()
                    self._publish(found)   # very first scan: show something while walking
            self._publish(found)

            todo = [e for e in found if e.kind != "file"
                    and (self.dates.get(e.path) or [None, None])[:2] != [int(e.m), e.size]]
            last = time.monotonic()
            for i, e in enumerate(todo):
                self.progress = {"phase": "dates", "found": len(found), "done": i, "total": len(todo), "dir": os.path.dirname(e.path)}
                t = taken(e)
                self.dates[e.path] = [int(e.m), e.size, round(t) if t else 0]
                if t:
                    e.t = t
                if i % 11 == 0:
                    self._seen(e.name)
                if time.monotonic() - last > 2.5:
                    last = time.monotonic()
                    self._publish(found)
            if todo:
                self._publish(found)
                live = {e.path for e in found}
                self.dates = {p: v for p, v in self.dates.items() if p in live}
                try:
                    tmp = self.dates_file.with_suffix(".tmp")
                    tmp.write_text(json.dumps(self.dates, separators=(",", ":")), "utf-8")
                    os.replace(tmp, self.dates_file)
                except OSError:
                    pass
        finally:
            self.progress = {"phase": "idle", "found": len(self.entries)}
            self.scanning = False

    def status(self) -> dict:
        return {**self.progress, "scanning": self.scanning, "recent": list(self.recent[-14:]),
                "scanned": int(self.scanned_at * 1000)}

    def ensure(self, max_age: float = 45) -> None:
        if time.time() - self.scanned_at > max_age:
            self.scan()

    def page(self, kind: str, q: str, offset: int, limit: int) -> dict:
        with self.lock:
            src = self.entries
        if kind == "media":
            src = [e for e in src if e.kind != "file"]
        elif kind in ("photo", "video", "file"):
            src = [e for e in src if e.kind == kind]
        if q:
            ql = q.lower()
            src = [e for e in src if ql in e.name.lower() or ql in os.path.basename(os.path.dirname(e.path)).lower()]
        counts = {"photo": 0, "video": 0, "file": 0}
        for e in self.entries:
            counts[e.kind] += 1
        return {"total": len(src), "offset": offset, "items": [e.public() for e in src[offset:offset + limit]],
                "counts": counts, "home": str(Path.home()), "scanning": self.scanning, "progress": self.status(), "scanned": int(self.scanned_at * 1000)}

    def get(self, eid: str) -> Entry | None:
        return self.by_id.get(eid)

    # ---- thumbnails ------------------------------------------------------- #
    def thumb(self, e: Entry) -> Path | None:
        """A small JPEG for the grid, made once and cached. None when it can't be made."""
        out = self.thumbs / f"{e.id}-{int(e.m)}.jpg"
        if out.exists():
            return out
        tmp = out.with_suffix(f".{threading.get_ident()}.part")
        try:
            if e.kind == "photo":
                if e.name.lower().endswith(".svg"):
                    return None
                from PIL import Image, ImageOps
                with Image.open(e.path) as im:
                    im.draft("RGB", (THUMB * 2, THUMB * 2))   # JPEGs decode straight to a small size
                    im = ImageOps.exif_transpose(im)
                    im.thumbnail((THUMB, THUMB))
                    if im.mode not in ("RGB", "L"):
                        bg = Image.new("RGB", im.size, (24, 24, 24))
                        im = im.convert("RGBA")
                        bg.paste(im, mask=im.split()[-1])
                        im = bg
                    im.save(tmp, "JPEG", quality=78)
            elif e.kind == "video" and self.ffmpeg:
                r = subprocess.run(
                    [self.ffmpeg, "-v", "error", "-ss", "1", "-i", e.path, "-frames:v", "1",
                     "-vf", f"scale={THUMB}:-2", "-q:v", "5", "-f", "mjpeg", "-y", str(tmp)],
                    capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                    subprocess.run(   # clips shorter than a second: take the very first frame
                        [self.ffmpeg, "-v", "error", "-i", e.path, "-frames:v", "1", "-vf", f"scale={THUMB}:-2",
                         "-q:v", "5", "-f", "mjpeg", "-y", str(tmp)],
                        capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                return None
            if tmp.exists() and tmp.stat().st_size > 0:
                os.replace(tmp, out)
                return out
        except Exception:
            pass
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        return None

    def prune_thumbs(self) -> None:
        """Removes thumbnails of files that no longer exist."""
        keep = {f"{e.id}-{int(e.m)}.jpg" for e in self.entries}
        try:
            for f in os.scandir(self.thumbs):
                if f.name not in keep:
                    try:
                        os.unlink(f.path)
                    except OSError:
                        pass
        except OSError:
            pass

    # ---- trash ------------------------------------------------------------ #
    def trash(self, ids: list[str]) -> tuple[int, list[str]]:
        """Moves files to the system Trash / Recycle Bin. Returns (moved, names that failed)."""
        moved, failed = 0, []
        for eid in ids:
            e = self.by_id.get(eid)
            if e is None:
                continue
            if trash_file(e.path):
                moved += 1
                with self.lock:
                    self.by_id.pop(eid, None)
            else:
                failed.append(e.name)
        with self.lock:
            self.entries = [e for e in self.entries if e.id in self.by_id]
        return moved, failed


def trash_file(path: str) -> bool:
    if not os.path.exists(path):
        return True
    try:
        if sys.platform.startswith("win"):
            return _trash_windows(path)
        if sys.platform == "darwin":
            script = f'tell application "Finder" to delete POSIX file "{path}"'
            return subprocess.run(["osascript", "-e", script], capture_output=True, timeout=30).returncode == 0
        if shutil.which("gio"):
            if subprocess.run(["gio", "trash", "--", path], capture_output=True, timeout=30).returncode == 0:
                return True
        return _trash_xdg(path)
    except Exception:
        return False


def _trash_xdg(path: str) -> bool:
    """The freedesktop.org Trash spec, for systems without gio. Home file system only."""
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "Trash"
    files, info = base / "files", base / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    if os.stat(path).st_dev != os.stat(files).st_dev:
        return False   # another drive: its own trash folder is needed, which gio handles
    name, n = os.path.basename(path), 1
    target = name
    while (files / target).exists() or (info / f"{target}.trashinfo").exists():
        stem, dot, ext = name.rpartition(".")
        target = f"{stem}.{n}.{ext}" if dot else f"{name}.{n}"
        n += 1
    (info / f"{target}.trashinfo").write_text(
        f"[Trash Info]\nPath={quote(os.path.abspath(path))}\nDeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n", "utf-8")
    os.rename(path, files / target)
    return True


def _trash_windows(path: str) -> bool:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                    ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_void_p)]

    FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT, FOF_NOERRORUI = 3, 0x40, 0x10, 0x4, 0x400
    # The path list must end with two nulls; the buffer adds one after the one written here.
    buf = ctypes.create_unicode_buffer(os.path.abspath(path) + "\0")
    op = SHFILEOPSTRUCTW(None, FO_DELETE, ctypes.cast(buf, ctypes.c_void_p), None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted
