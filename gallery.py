"""The Gallery: every photo, video and file in the folders you choose, newest first.

Everything stays on this computer. The index lives in memory, thumbnails are cached in
~/.tonefer/thumbs, and "delete" always means the system Trash, so it can be undone.
"""

from __future__ import annotations

import hashlib
import os
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
    __slots__ = ("id", "path", "name", "t", "size", "kind")

    def __init__(self, path: str, name: str, t: float, size: int, kind: str):
        self.id = hashlib.sha1(path.encode("utf-8", "surrogatepass")).hexdigest()[:16]
        self.path, self.name, self.t, self.size, self.kind = path, name, t, size, kind

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "t": int(self.t * 1000), "size": self.size, "kind": self.kind,
                "dir": os.path.dirname(self.path)}


class Gallery:
    def __init__(self, app_dir: Path, config):
        self.config = config
        self.thumbs = app_dir / "thumbs"
        self.thumbs.mkdir(parents=True, exist_ok=True)
        self.entries: list[Entry] = []
        self.by_id: dict[str, Entry] = {}
        self.scanning = False
        self.scanned_at = 0.0
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
    def scan(self) -> None:
        """Walks the chosen folders. Fast: one stat per file, no file is opened."""
        if self.scanning:
            return
        self.scanning = True
        try:
            found: list[Entry] = []
            stack = [str(r) for r in self.roots()]
            while stack:
                d = stack.pop()
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
                                found.append(Entry(e.path, name, st.st_mtime, st.st_size, kind))
                            except OSError:
                                continue
                except OSError:
                    continue
            found.sort(key=lambda x: x.t, reverse=True)
            with self.lock:
                self.entries = found
                self.by_id = {e.id: e for e in found}
                self.scanned_at = time.time()
        finally:
            self.scanning = False

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
                "counts": counts, "home": str(Path.home()), "scanning": self.scanning, "scanned": int(self.scanned_at * 1000)}

    def get(self, eid: str) -> Entry | None:
        return self.by_id.get(eid)

    # ---- thumbnails ------------------------------------------------------- #
    def thumb(self, e: Entry) -> Path | None:
        """A small JPEG for the grid, made once and cached. None when it can't be made."""
        out = self.thumbs / f"{e.id}-{int(e.t)}.jpg"
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
        keep = {f"{e.id}-{int(e.t)}.jpg" for e in self.entries}
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
