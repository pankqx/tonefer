"""Tonefer laptop server.

Runs on the laptop. Serves two UIs:
  * /desk  - the laptop UI, reachable ONLY from this machine (loopback)
  * /      - the phone UI, reachable over the local network (phone hotspot)

Everything the phone sends or receives is end-to-end encrypted with a 32-byte
key that is shared once, by scanning a QR code (the key travels in the URL
fragment, which browsers never send to a server). Anything that does not
decrypt with that key is rejected.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import platform
import shutil
import struct
import subprocess
import sys
import time
import uuid
import webbrowser
from io import BytesIO
from pathlib import Path

import nacl.exceptions
import nacl.secret
import nacl.utils
import netinfo
import qrcode
import qrcode.image.svg
import gallery as gal
import transfer as tx
import update as up
from aiohttp import WSMsgType, web

def _read_version() -> str:
    try:
        return (Path(__file__).resolve().parent / "VERSION").read_text().strip()
    except OSError:
        return "dev"


VERSION = _read_version()
APP_DIR = Path(os.environ.get("TONEFER_HOME", Path.home() / ".tonefer"))
FILES_DIR = Path(os.environ.get("TONEFER_FILES", Path.home() / "Tonefer"))
PORT = int(os.environ.get("TONEFER_PORT", "8765"))
WEB = Path(__file__).resolve().parent / "web"
MAX_FILE = 512 * 1024 * 1024  # cap for the old single-request upload; chunked transfers have none
PARTIAL = APP_DIR / "partial"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


# --------------------------------------------------------------------------- #
# Crypto
# --------------------------------------------------------------------------- #
class Key:
    """A 32-byte secret shared with a phone, and everything derived from it."""

    key: bytes

    @property
    def box(self) -> nacl.secret.SecretBox:
        return nacl.secret.SecretBox(self.key)

    @property
    def token(self) -> str:
        # Access gate only. Real protection is the key: payloads must decrypt.
        return hashlib.sha512(self.key + b"tonefer-auth").hexdigest()[:64]

    @property
    def key_b64(self) -> str:
        return base64.urlsafe_b64encode(self.key).decode().rstrip("=")

    def seal(self, data: bytes) -> bytes:
        return bytes(self.box.encrypt(data))  # nonce(24) || ciphertext

    def open(self, data: bytes) -> bytes:
        return self.box.decrypt(data)

    def seal_json(self, obj) -> str:
        return base64.b64encode(self.seal(json.dumps(obj).encode())).decode()

    def open_json(self, s: str):
        return json.loads(self.open(base64.b64decode(s)))


class Vault(Key):
    """Holds the owner's pairing key. Rotating it unpairs every phone."""

    def __init__(self, path: Path):
        self.path = path
        if path.exists() and len(path.read_bytes()) == 32:
            self.key = path.read_bytes()
        else:
            self.rotate()

    def rotate(self) -> None:
        self.key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self.key)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


GUEST_HOURS = 12


class Guest(Key):
    """A guest session: a friend's phone gets its own key and sees only its own transfers.
    Ending the session (or its expiry) cuts that phone off without touching yours."""

    def __init__(self, name: str, gid: str | None = None, key: bytes | None = None, expires: float | None = None):
        self.id = gid or uuid.uuid4().hex[:8]
        self.name = name
        self.key = key or nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)
        self.expires = expires or time.time() + GUEST_HOURS * 3600

    def dump(self) -> dict:
        return {"id": self.id, "name": self.name, "key": base64.b64encode(self.key).decode(), "expires": self.expires}

    @staticmethod
    def load(d: dict) -> "Guest":
        return Guest(d["name"], d["id"], base64.b64decode(d["key"]), d["expires"])


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
class History:
    def __init__(self, path: Path):
        self.path = path
        self.items: list[dict] = []
        if path.exists():
            try:
                self.items = json.loads(path.read_text("utf-8"))
            except (ValueError, OSError):
                self.items = []

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, ensure_ascii=False), "utf-8")
        tmp.replace(self.path)

    def add(self, item: dict) -> dict:
        self.items.append(item)
        self.save()
        return item

    def get(self, item_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    def remove(self, item_id: str) -> dict | None:
        item = self.get(item_id)
        if item:
            self.items.remove(item)
            self.save()
        return item

    def clear(self) -> None:
        self.items = []
        self.save()

    @staticmethod
    def public(item: dict) -> dict:
        return {k: v for k, v in item.items() if k != "path"}

    def public_list(self) -> list[dict]:
        return [self.public(i) for i in self.items]


def new_item(kind: str, origin: str, **extra) -> dict:
    return {"id": uuid.uuid4().hex[:16], "kind": kind, "origin": origin,
            "ts": int(time.time() * 1000), **extra}


def safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name.strip() or "file"
    bad = '<>:"/\\|?*\x00'
    name = "".join("_" if c in bad or ord(c) < 32 else c for c in name)
    return name[:180]


def unique_path(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    stem, suffix, n = p.stem, p.suffix, 1
    while p.exists():
        p = folder / f"{stem} ({n}){suffix}"
        n += 1
    return p


def lan_addresses() -> list[str]:
    return [d["ip"] for d in netinfo.addresses()]


# --------------------------------------------------------------------------- #
# Transfer speed
# --------------------------------------------------------------------------- #
class Meter:
    """Measures real bytes/second of one network transfer and reports it live to the laptop UI.

    dir "in"  = phone → laptop,  dir "out" = laptop → phone.
    """

    def __init__(self, app: "Tonefer", direction: str, total: int, label: str):
        self.app, self.dir, self.total, self.label = app, direction, total, label
        self.id = uuid.uuid4().hex[:8]
        self.start = time.monotonic()
        self.bytes = 0
        self.samples: list[tuple[float, int]] = [(self.start, 0)]
        self.last_emit = 0.0

    def rate(self, now: float) -> float:
        # Rate over the last ~1.2 s, so the needle follows the live speed.
        while len(self.samples) > 2 and now - self.samples[0][0] > 1.2:
            self.samples.pop(0)
        t0, b0 = self.samples[0]
        return (self.bytes - b0) / max(now - t0, 1e-3)

    async def add(self, n: int) -> None:
        self.bytes += n
        now = time.monotonic()
        self.samples.append((now, self.bytes))
        if now - self.last_emit >= 0.2:
            self.last_emit = now
            await self.app.desk_send({"type": "rate", "id": self.id, "dir": self.dir, "label": self.label,
                                      "bps": self.rate(now), "bytes": self.bytes, "total": self.total,
                                      "done": False})

    async def finish(self) -> float:
        elapsed = max(time.monotonic() - self.start, 1e-3)
        avg = self.bytes / elapsed
        await self.app.desk_send({"type": "rate", "id": self.id, "dir": self.dir, "label": self.label,
                                  "bps": avg, "bytes": self.bytes, "total": self.total, "done": True,
                                  "seconds": elapsed})
        return avg


SPEEDTEST_BYTES = 16 * 1024 * 1024
_NOISE = os.urandom(256 * 1024)


# --------------------------------------------------------------------------- #
# Settings stored on the laptop (~/.tonefer/config.json)
# --------------------------------------------------------------------------- #
class Config:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, **values) -> None:
        self.data.update(values)
        self.path.write_text(json.dumps(self.data, indent=2), "utf-8")


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
class Tonefer:
    def __init__(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        FILES_DIR.mkdir(parents=True, exist_ok=True)
        self.vault = Vault(APP_DIR / "pairing.key")
        self.history = History(APP_DIR / "history.json")
        self.phones: dict[web.WebSocketResponse, str | None] = {}   # socket -> guest id (None = owner)
        self.guests: dict[str, Guest] = {}
        try:
            for d in json.loads((APP_DIR / "guests.json").read_text("utf-8")):
                g = Guest.load(d)
                if g.expires > time.time():
                    self.guests[g.id] = g
        except (OSError, ValueError, KeyError):
            pass
        self.desks: set[web.WebSocketResponse] = set()
        self._net_checked = -1e9
        self._net_cache: dict = {}
        self.config = Config(APP_DIR / "config.json")
        self.hotspot_status = ""
        self.downloads = 0   # laptop → phone streams in flight
        self.gallery = gal.Gallery(APP_DIR, self.config)
        self.thumb_slots = asyncio.Semaphore(4)
        self.latest: str | None = None   # newest published version, once checked
        self.updating = False
        self.uploads: dict[str, tx.Incoming] = {}
        self.zips: dict[str, tx.ZipBuild] = {}
        shutil.rmtree(PARTIAL, ignore_errors=True)  # leftovers from a crash
        PARTIAL.mkdir(parents=True, exist_ok=True)

    # ---- broadcasting --------------------------------------------------- #
    def key_of(self, sid: str | None) -> Key | None:
        return self.vault if sid is None else self.guests.get(sid)

    def save_guests(self) -> None:
        path = APP_DIR / "guests.json"
        path.write_text(json.dumps([g.dump() for g in self.guests.values()]), "utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    async def to_phones(self, event: dict, sid: str | None = "*") -> None:
        """Sends an event to phones, sealed with each phone's own key. sid "*" = every session."""
        sealed: dict[str | None, str] = {}
        for ws, s in list(self.phones.items()):
            if sid != "*" and s != sid:
                continue
            key = self.key_of(s)
            if key is None:
                continue
            if s not in sealed:
                sealed[s] = key.seal_json(event)
            try:
                await ws.send_str(sealed[s])
            except Exception:
                self.phones.pop(ws, None)

    async def broadcast(self, event: dict, sid: str | None = "*") -> None:
        await self.desk_send(event)
        await self.to_phones(event, sid)

    async def desk_send(self, event: dict) -> None:
        msg = json.dumps(event)
        for ws in list(self.desks):
            try:
                await ws.send_str(msg)
            except Exception:
                self.desks.discard(ws)

    async def announce_presence(self) -> None:
        msg = json.dumps({"type": "presence", "phones": len(self.phones), "guests": self.guest_list()})
        for ws in list(self.desks):
            try:
                await ws.send_str(msg)
            except Exception:
                self.desks.discard(ws)

    async def publish(self, item: dict) -> dict:
        self.history.add(item)
        # Each phone only hears about its own session's items; the laptop sees everything.
        await self.broadcast({"type": "item", "item": History.public(item)}, item.get("session"))
        return item

    def guest_list(self) -> list[dict]:
        online = list(self.phones.values())
        return [{"id": g.id, "name": g.name, "expires": int(g.expires * 1000), "online": online.count(g.id)}
                for g in self.guests.values()]

    # ---- where files live ------------------------------------------------ #
    def recv_dir(self, sid: str | None = None) -> Path:
        base = Path(self.config.get("received_dir") or FILES_DIR / "Received")
        g = self.guests.get(sid) if sid else None
        return base / f"Guest {safe_name(g.name)}" if g else base

    @staticmethod
    def rel(dest: Path) -> str:
        """Stored path: relative inside the Tonefer folder, absolute anywhere else."""
        try:
            return str(dest.relative_to(FILES_DIR))
        except ValueError:
            return str(dest)

    @staticmethod
    def tag(sid: str | None) -> dict:
        return {"session": sid} if sid else {}

    def store_file(self, folder: Path, name: str, data: bytes, mime: str | None, origin: str, sid: str | None = None) -> dict:
        name = safe_name(name)
        dest = unique_path(folder, name)
        dest.write_bytes(data)
        mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return new_item("file", origin, name=dest.name, size=len(data), mime=mime, path=self.rel(dest), **self.tag(sid))

    # ---- middleware ----------------------------------------------------- #
    @web.middleware
    async def guard(self, request: web.Request, handler):
        if request.path.startswith("/desk"):
            # Laptop UI: loopback only, and a localhost Host header
            # (blocks other devices and DNS-rebinding tricks).
            host = (request.host or "").rsplit(":", 1)[0]
            if request.remote not in ("127.0.0.1", "::1") or host not in LOCAL_HOSTS:
                raise web.HTTPForbidden(text="The laptop view is only available on this computer.")
            # Web pages from other sites can still aim requests at 127.0.0.1; browsers label
            # those with their Origin, so anything not from the laptop view itself is refused.
            origin = request.headers.get("Origin")
            if origin and origin != "null":
                from urllib.parse import urlsplit
                if (urlsplit(origin).hostname or "") not in LOCAL_HOSTS | {"::1"}:
                    raise web.HTTPForbidden(text="Requests from other websites aren't allowed.")
        elif request.path.startswith("/api") or request.path == "/ws":
            token = request.headers.get("X-Tonefer-Token") or request.query.get("t", "")
            if secrets_equal(token, self.vault.token):
                request["key"], request["sid"] = self.vault, None
            else:
                now = time.time()
                g = next((g for g in self.guests.values() if g.expires > now and secrets_equal(token, g.token)), None)
                if g is None:
                    raise web.HTTPUnauthorized(text="Not paired. Scan the QR code on your laptop.")
                request["key"], request["sid"] = g, g.id
        resp = await handler(request)
        if getattr(resp, "prepared", False):
            return resp
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    # ---- phone side ----------------------------------------------------- #
    async def phone_index(self, request):
        return web.FileResponse(WEB / "phone" / "index.html")

    async def phone_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=45, max_msg_size=4 * 1024 * 1024)  # generous: a busy upload delays pongs
        await ws.prepare(request)
        key, sid = request["key"], request["sid"]
        self.phones[ws] = sid
        await self.announce_presence()
        hello = {"type": "hello", "host": platform.node(),
                 "items": [History.public(i) for i in self.history.items if i.get("session") == sid]}
        if sid:
            hello["guest"] = key.name
        await ws.send_str(key.seal_json(hello))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = key.open_json(msg.data)
                except (nacl.exceptions.CryptoError, ValueError):
                    await ws.close(code=4001, message=b"bad key")
                    break
                if data.get("type") == "text":
                    text = str(data.get("text", ""))[:100_000]
                    if text.strip():
                        await self.publish(new_item("text", "phone", text=text, **self.tag(sid)))
        finally:
            self.phones.pop(ws, None)
            await self.announce_presence()
        return ws

    async def phone_ping(self, request):
        return web.json_response({"ok": True, "version": VERSION})

    async def phone_upload(self, request):
        if request.content_length and request.content_length > MAX_FILE + 1024:
            raise web.HTTPRequestEntityTooLarge(MAX_FILE, request.content_length)
        key, sid = request["key"], request["sid"]
        try:
            meta = key.open_json(request.headers.get("X-Tonefer-Meta", ""))
        except (nacl.exceptions.CryptoError, ValueError):
            raise web.HTTPForbidden(text="Payload did not decrypt. Re-pair your phone.")
        name = str(meta.get("name", "file"))
        meter = Meter(self, "in", request.content_length or 0, name)
        buf = bytearray()
        async for chunk in request.content.iter_chunked(64 * 1024):
            buf += chunk
            if len(buf) > MAX_FILE + 1024:
                raise web.HTTPRequestEntityTooLarge(MAX_FILE, len(buf))
            await meter.add(len(chunk))
        await meter.finish()
        try:
            data = await asyncio.to_thread(key.open, bytes(buf))
        except (nacl.exceptions.CryptoError, ValueError):
            raise web.HTTPForbidden(text="Payload did not decrypt. Re-pair your phone.")
        item = self.store_file(self.recv_dir(sid), name, data, meta.get("mime"), "phone", sid)
        await self.publish(item)
        return web.json_response({"ok": True, "id": item["id"]})

    async def phone_file(self, request):
        item = self.history.get(request.match_info["id"])
        if not item or item["kind"] != "file" or item.get("session") != request["sid"]:
            raise web.HTTPNotFound()
        path = FILES_DIR / item["path"]
        if not path.exists():
            raise web.HTTPGone(text="File was moved or deleted on the laptop.")
        if request.query.get("v") == "2":
            return await self.stream_file(request, item, path)
        if path.stat().st_size > MAX_FILE:
            raise web.HTTPRequestEntityTooLarge(MAX_FILE, path.stat().st_size,
                                                text="Update Tonefer on your phone to receive files this big.")
        data = await asyncio.to_thread(path.read_bytes)
        sealed = await asyncio.to_thread(request["key"].seal, data)
        return await self.stream_out(request, sealed, item["name"])

    async def stream_out(self, request, payload, label: str, total: int | None = None):
        """Sends bytes to the phone in chunks, measuring the real network speed."""
        size = total if total is not None else len(payload)
        resp = web.StreamResponse(headers={"Content-Type": "application/octet-stream", "Cache-Control": "no-store"})
        resp.content_length = size
        await resp.prepare(request)
        meter = Meter(self, "out", size, label)
        step = 256 * 1024
        sent = 0
        while sent < size:
            n = min(step, size - sent)
            chunk = payload[sent:sent + n] if total is None else _NOISE[:n]
            await resp.write(chunk)
            sent += n
            await meter.add(n)
        await resp.write_eof()
        await meter.finish()
        return resp

    async def phone_speed_down(self, request):
        n = min(int(request.query.get("n", SPEEDTEST_BYTES)), 128 * 1024 * 1024)
        return await self.stream_out(request, None, "Speed test", total=n)

    async def phone_speed_up(self, request):
        meter = Meter(self, "in", request.content_length or 0, "Speed test")
        async for chunk in request.content.iter_chunked(64 * 1024):
            await meter.add(len(chunk))
        bps = await meter.finish()
        return web.json_response({"ok": True, "bps": bps})

    # ---- big transfers (protocol v2) ------------------------------------ #
    def _meta(self, request, raw: str) -> dict:
        try:
            meta = request["key"].open_json(raw.strip())
        except (nacl.exceptions.CryptoError, ValueError, TypeError):
            raise web.HTTPForbidden(text="Payload did not decrypt. Re-pair your phone.")
        if not isinstance(meta, dict):
            raise web.HTTPBadRequest(text="Bad request")
        return meta

    @staticmethod
    def _int(v, default: int = -1) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    async def stream_file(self, request, item: dict, path: Path):
        """Laptop → phone, any size: length-prefixed frames, each sealed on its own."""
        size = path.stat().st_size
        frames = max(1, -(-size // tx.DCHUNK))
        start = min(max(self._int(request.query.get("from"), 0), 0), frames)
        resp = web.StreamResponse(headers={
            "Content-Type": "application/octet-stream", "Cache-Control": "no-store",
            "X-Tonefer-Format": "2", "X-Tonefer-Size": str(size), "X-Tonefer-Frames": str(frames),
            "X-Tonefer-Chunk": str(tx.DCHUNK)})
        resp.content_length = tx.frames_size(size, start)
        await resp.prepare(request)
        meter = Meter(self, "out", max(size - start * tx.DCHUNK, 0), item["name"])
        tid = item["id"]
        key = request["key"]

        def frame(fh, i: int) -> bytes:
            sealed = key.seal(tx.header(tid, i, i == frames - 1) + fh.read(tx.DCHUNK))
            return struct.pack(">I", len(sealed)) + sealed

        self.downloads += 1
        try:
            with open(path, "rb") as fh:
                fh.seek(start * tx.DCHUNK)
                for i in range(start, frames):
                    out = await asyncio.to_thread(frame, fh, i)
                    await resp.write(out)
                    await meter.add(len(out) - tx.FRAME_OVERHEAD)
        finally:
            self.downloads -= 1
        await resp.write_eof()
        await meter.finish()
        return resp

    async def phone_zip_start(self, request):
        meta = self._meta(request, await request.text())
        self.need_space(self._int(meta.get("size")), self.recv_dir(request["sid"]))
        zid = tx.new_id()
        z = await asyncio.to_thread(tx.ZipBuild, zid, str(meta.get("name") or "Tonefer"), "phone", PARTIAL,
                                    self._int(meta.get("files"), 0), self._int(meta.get("size")))
        z.meter = Meter(self, "in", max(z.expected_size, 0), z.name)
        z.sid = request["sid"]
        self.zips[zid] = z
        return web.json_response({"zip": zid, "name": z.name})

    def need_space(self, size: int, where: Path) -> None:
        """Refuses a transfer the disk can't hold, with a message the phone shows as it is."""
        if size <= 0:
            return
        try:
            where.mkdir(parents=True, exist_ok=True)
            free = min(shutil.disk_usage(where).free, shutil.disk_usage(PARTIAL).free)
        except OSError:
            return
        if free < size + (200 << 20):
            raise web.HTTPInsufficientStorage(
                text=f"The laptop's disk is too full: {free / 1e9:.1f} GB free, {size / 1e9:.1f} GB needed")

    async def phone_upload_start(self, request):
        meta = self._meta(request, await request.text())
        name = safe_name(str(meta.get("name") or "file"))
        size = self._int(meta.get("size"))
        if not meta.get("zip"):
            self.need_space(size, self.recv_dir(request["sid"]))
        mime = str(meta.get("mime") or "") or mimetypes.guess_type(name)[0] or "application/octet-stream"
        tid = tx.new_id()
        zid = meta.get("zip")
        if zid:
            z = self.zips.get(str(zid))
            if z is None or z.zf is None or z.sid != request["sid"]:
                raise web.HTTPNotFound(text="That zip is no longer open. Send the folder again.")
            async with z.lock:
                busy = self.uploads.get(z.owner or "")
                if busy is not None and not busy.done:
                    return web.json_response({"ok": False, "busy": busy.id, "next": busy.next}, status=409)
                mtime = self._int(meta.get("mtime"), 0) / 1000 or None
                await asyncio.to_thread(z.open_entry, str(meta.get("path") or name), size, mtime)
                z.owner = tid
                z.last_seen = time.monotonic()
            inc = tx.Incoming(tid, name, mime, size, "phone", zipb=z)
            inc.meter = z.meter
        else:
            tmp = PARTIAL / f"{tid}.part"
            inc = tx.Incoming(tid, name, mime, size, "phone", tmp=tmp)
            inc.fh = await asyncio.to_thread(open, tmp, "wb")
            inc.meter = Meter(self, "in", max(size, 0), name)
        inc.sid = request["sid"]
        self.uploads[tid] = inc
        return web.json_response({"id": tid, "chunk": tx.CHUNK, "next": 0})

    async def phone_upload_state(self, request):
        inc = self.uploads.get(request.match_info["tid"])
        if inc is None or inc.sid != request["sid"]:
            raise web.HTTPNotFound(text="Unknown transfer")
        return web.json_response({"next": inc.next, "done": inc.done, "bytes": inc.bytes})

    async def phone_upload_chunk(self, request):
        tid = request.match_info["tid"]
        inc = self.uploads.get(tid)
        if inc is None or inc.sid != request["sid"]:
            raise web.HTTPNotFound(text="Unknown transfer. Send the file again.")
        index = self._int(request.match_info["index"])
        limit = tx.CHUNK + 4096
        if (request.content_length or 0) > limit:
            raise web.HTTPRequestEntityTooLarge(limit, request.content_length)
        buf = bytearray()
        async for part in request.content.iter_chunked(256 * 1024):
            buf += part
            if len(buf) > limit:
                raise web.HTTPRequestEntityTooLarge(limit, len(buf))
            await inc.meter.add(len(part))  # live speed while the chunk is still arriving
        async with inc.lock:
            now = time.monotonic()
            inc.last_seen = now
            if inc.zip is not None:
                inc.zip.last_seen = now
            if index < inc.next:  # a retry of something we already have
                return web.json_response({"ok": True, "next": inc.next, "done": inc.done})
            if index > inc.next or inc.done:
                return web.json_response({"ok": False, "next": inc.next, "done": inc.done}, status=409)
            try:
                plain = await asyncio.to_thread(request["key"].open, bytes(buf))
            except (nacl.exceptions.CryptoError, ValueError):
                raise web.HTTPForbidden(text="Payload did not decrypt. Re-pair your phone.")
            ctid, cindex, last, data = tx.parse(plain)
            if ctid != tid or cindex != index:
                raise web.HTTPBadRequest(text="That chunk belongs to another transfer.")
            await asyncio.to_thread(inc.write, data)
            inc.next += 1
            result = {"ok": True, "next": inc.next, "done": False}
            if last:
                await asyncio.to_thread(inc.close)
                inc.done = True
                result["done"] = True
                if inc.zip is None:
                    await inc.meter.finish()
                    item = await asyncio.to_thread(self.finish_file, inc, self.recv_dir(inc.sid))
                    await self.publish(item)
                    result["item"] = item["id"]
            return web.json_response(result)

    def finish_file(self, inc: tx.Incoming, folder: Path) -> dict:
        dest = unique_path(folder, safe_name(inc.name))
        shutil.move(str(inc.tmp), dest)
        return new_item("file", inc.origin, name=dest.name, size=dest.stat().st_size, mime=inc.mime,
                        path=self.rel(dest), **self.tag(inc.sid))

    async def finish_zip(self, z: tx.ZipBuild, folder: Path) -> dict:
        tmp = await asyncio.to_thread(z.finish)
        z.zf = None
        dest = unique_path(folder, z.name)
        await asyncio.to_thread(shutil.move, str(tmp), dest)
        if z.meter is not None:
            await z.meter.finish()
        item = new_item("file", z.origin, name=dest.name, size=dest.stat().st_size, mime="application/zip",
                        path=self.rel(dest), files=z.count, **self.tag(z.sid))
        z.item = item["id"]
        await self.publish(item)
        return item

    async def phone_zip_finish(self, request):
        self._meta(request, await request.text())  # proves the sender has the key
        z = self.zips.get(request.match_info["zid"])
        if z is None or z.sid != request["sid"]:
            raise web.HTTPNotFound(text="That zip is no longer open. Send the folder again.")
        async with z.lock:
            if getattr(z, "item", None):  # already finished (a retry)
                return web.json_response({"ok": True, "item": z.item})
            busy = self.uploads.get(z.owner or "")
            if busy is not None and not busy.done:
                return web.json_response({"ok": False, "busy": busy.id, "next": busy.next}, status=409)
            item = await self.finish_zip(z, self.recv_dir(z.sid))
        for tid in [t for t, inc in self.uploads.items() if inc.zip is z]:
            self.uploads.pop(tid, None)
        return web.json_response({"ok": True, "item": item["id"]})

    async def phone_upload_cancel(self, request):
        inc = self.uploads.get(request.match_info["tid"])
        if inc is not None and inc.sid != request["sid"]:
            inc = None
        else:
            self.uploads.pop(request.match_info["tid"], None)
        if inc is not None and inc.zip is None and not inc.done:
            await asyncio.to_thread(inc.abort)
            await inc.meter.finish()
        return web.json_response({"ok": True})

    async def phone_zip_cancel(self, request):
        z = self.zips.get(request.match_info["zid"])
        if z is not None and z.sid != request["sid"]:
            z = None
        else:
            self.zips.pop(request.match_info["zid"], None)
        if z is not None and z.zf is not None:
            for tid in [t for t, inc in self.uploads.items() if inc.zip is z]:
                self.uploads.pop(tid, None)
            await asyncio.to_thread(z.abort)
            if z.meter is not None:
                await z.meter.finish()
        return web.json_response({"ok": True})

    async def stay_awake(self) -> None:
        """Keeps the laptop from going to sleep while a transfer is moving."""
        proc = None
        try:
            while True:
                await asyncio.sleep(10)
                now = time.monotonic()
                busy = self.downloads > 0 or any(not i.done and now - i.last_seen < 90 for i in self.uploads.values())
                if sys.platform.startswith("win"):
                    try:
                        import ctypes
                        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if busy else 0x80000000)
                    except Exception:
                        pass
                elif busy and proc is None and shutil.which("systemd-inhibit"):
                    proc = subprocess.Popen(["systemd-inhibit", "--what=sleep:idle", "--who=Tonefer",
                                             "--why=Transfer in progress", "sleep", "infinity"],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif not busy and proc is not None:
                    proc.terminate()
                    proc = None
        finally:
            if proc is not None:
                proc.terminate()

    async def janitor(self) -> None:
        """Drops transfers the phone walked away from, so half files don't pile up."""
        while True:
            await asyncio.sleep(60)
            for g in [g for g in self.guests.values() if g.expires <= time.time()]:
                await self.end_guest(g.id)
            now = time.monotonic()
            for tid, inc in list(self.uploads.items()):
                age = now - inc.last_seen
                if (inc.done and age > 600) or age > tx.STALE_SECONDS:
                    self.uploads.pop(tid, None)
                    if not inc.done and inc.zip is None:
                        await asyncio.to_thread(inc.abort)
            for zid, z in list(self.zips.items()):
                age = now - z.last_seen
                if (z.zf is None and age > 600) or age > tx.STALE_SECONDS:
                    self.zips.pop(zid, None)
                    if z.zf is not None:
                        await asyncio.to_thread(z.abort)

    # ---- laptop side ---------------------------------------------------- #
    async def desk_index(self, request):
        return web.FileResponse(WEB / "desk" / "index.html")

    async def desk_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.desks.add(ws)
        await ws.send_str(json.dumps({"type": "hello", "host": platform.node(),
                                      "items": self.history.public_list(), "guests": self.guest_list(),
                                      "update": self.update_info(),
                                      "phones": len(self.phones), "version": VERSION}))
        try:
            async for _ in ws:
                pass
        finally:
            self.desks.discard(ws)
        return ws

    async def desk_text(self, request):
        body = await request.json()
        text = str(body.get("text", ""))[:100_000]
        if not text.strip():
            raise web.HTTPBadRequest(text="Empty message")
        item = await self.publish(new_item("text", "laptop", text=text, **self.tag(self.target(body.get("to")))))
        return web.json_response(History.public(item))

    def target(self, to) -> str | None:
        """Which session a laptop → phone item is for: a guest id, or None for your own phone."""
        return to if to and to in self.guests else None

    async def desk_upload(self, request):
        """Laptop → phone. Streams straight to disk (no size limit). With ?zip=Name, every file
        goes into one archive; each file part may be preceded by "path", "size" and "mtime" fields."""
        reader = await request.multipart()
        zname = request.query.get("zip")
        z = await asyncio.to_thread(tx.ZipBuild, tx.new_id(), zname, "laptop", PARTIAL) if zname else None
        to = self.target(request.query.get("to"))
        if z is not None:
            z.sid = to
        sent: list[dict] = []
        fields: dict[str, str] = {}
        try:
            while (part := await reader.next()) is not None:
                if not part.filename:
                    fields[part.name or ""] = (await part.text()).strip()
                    continue
                size = self._int(fields.get("size"))
                mtime = self._int(fields.get("mtime"), 0) / 1000 or None
                if z is not None:
                    await asyncio.to_thread(z.open_entry, fields.get("path") or part.filename, size, mtime)
                    while chunk := await part.read_chunk(1 << 20):
                        await asyncio.to_thread(z.write, chunk)
                    await asyncio.to_thread(z.close_entry)
                else:
                    name = safe_name(part.filename)
                    dest = unique_path(FILES_DIR / "Sent", name)
                    fh = await asyncio.to_thread(open, dest, "wb")
                    try:
                        while chunk := await part.read_chunk(1 << 20):
                            await asyncio.to_thread(fh.write, chunk)
                    finally:
                        fh.close()
                    mime = part.headers.get("Content-Type")
                    if not mime or mime == "application/octet-stream":
                        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                    item = new_item("file", "laptop", name=dest.name, size=dest.stat().st_size, mime=mime,
                                    path=self.rel(dest), **self.tag(to))
                    await self.publish(item)
                    sent.append(History.public(item))
                fields = {}
            if z is not None:
                if z.count == 0:
                    raise web.HTTPBadRequest(text="Nothing to zip")
                sent.append(History.public(await self.finish_zip(z, FILES_DIR / "Sent")))
        except BaseException:
            if z is not None and z.zf is not None:
                await asyncio.to_thread(z.abort)
            raise
        return web.json_response(sent)

    async def desk_send_folder(self, request):
        """Opens the system folder picker, zips the chosen folder and offers it to the phone."""
        body = await request.json() if request.can_read_body else {}
        path = (body or {}).get("path")
        if not path:
            path = await asyncio.to_thread(tx.pick_folder)
            if path is None:
                return web.json_response({"picker": False}, status=501)
            if not path:
                return web.json_response({"cancelled": True})
        src = Path(path).expanduser()
        if not src.is_dir():
            raise web.HTTPBadRequest(text="That isn't a folder.")
        name = tx.zip_name(src.name or "Folder")
        pid = tx.new_id()
        tmp = PARTIAL / f"{pid}.zip.part"
        loop = asyncio.get_running_loop()
        last = [0.0]

        def progress(done: int, total: int, files: int) -> None:
            now = time.monotonic()
            if now - last[0] < 0.25 and done < total:
                return
            last[0] = now
            event = {"type": "zipping", "id": pid, "name": name, "done": done, "total": total, "files": files}
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.desk_send(event)))

        await self.desk_send({"type": "zipping", "id": pid, "name": name, "done": 0, "total": 0, "files": 0})
        try:
            count, _ = await asyncio.to_thread(tx.zip_folder, src, tmp, progress)
            if count == 0:
                raise ValueError("the folder is empty")
            dest = unique_path(FILES_DIR / "Sent", name)
            await asyncio.to_thread(shutil.move, str(tmp), dest)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            await self.desk_send({"type": "zipping", "id": pid, "name": name, "finished": True, "error": str(e)})
            raise web.HTTPBadRequest(text=f"Couldn't zip {src.name}: {e}")
        await self.desk_send({"type": "zipping", "id": pid, "name": name, "finished": True})
        item = new_item("file", "laptop", name=dest.name, size=dest.stat().st_size, mime="application/zip",
                        path=self.rel(dest), files=count, **self.tag(self.target((body or {}).get("to"))))
        await self.publish(item)
        return web.json_response(History.public(item))

    # ---- gallery ---------------------------------------------------------- #
    async def rescan_gallery(self) -> None:
        try:
            await asyncio.to_thread(self.gallery.scan)
        except Exception as e:
            print(f"gallery scan failed: {e}", file=sys.stderr)
            self.gallery.scanning = False
            return
        await self.desk_send({"type": "gallery", "scanned": int(self.gallery.scanned_at * 1000)})
        await asyncio.to_thread(self.gallery.prune_thumbs)

    async def desk_gallery(self, request):
        g = self.gallery
        offset = max(self._int(request.query.get("offset"), 0), 0)
        # Never make the page wait for a scan: answer with what is known, refresh behind.
        if not g.scanning and (g.scanned_at == 0 or (offset == 0 and (request.query.get("fresh") or time.time() - g.scanned_at > 45))):
            asyncio.ensure_future(self.rescan_gallery())
            await asyncio.sleep(0.05)
        limit = min(max(self._int(request.query.get("limit"), 600), 1), 5000)
        try:
            return web.json_response(g.page(request.query.get("kind", "media"), request.query.get("q", "").strip(), offset, limit))
        except Exception as e:
            return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=500)

    async def desk_gallery_status(self, request):
        return web.json_response(self.gallery.status())

    def _entry(self, request) -> gal.Entry:
        e = self.gallery.get(request.match_info["id"])
        if e is None or not os.path.exists(e.path):
            raise web.HTTPNotFound()
        return e

    async def desk_thumb(self, request):
        e = self._entry(request)
        async with self.thumb_slots:
            path = await asyncio.to_thread(self.gallery.thumb, e)
        cache = {"Cache-Control": "private, max-age=604800, immutable"}
        if path is not None:
            return web.FileResponse(path, headers={**cache, "Content-Type": "image/jpeg"})
        if e.kind == "photo":
            return web.FileResponse(e.path, headers=cache)   # no thumbnailer for this type: send the picture
        raise web.HTTPNotFound()

    async def desk_media(self, request):
        e = self._entry(request)
        mime = mimetypes.guess_type(e.name)[0] or "application/octet-stream"
        # FileResponse answers byte ranges, which is what makes video start and seek instantly.
        return web.FileResponse(e.path, headers={"Content-Type": mime, "Cache-Control": "private, max-age=3600"})

    async def desk_gallery_trash(self, request):
        ids = [str(i) for i in (await request.json()).get("ids", [])][:5000]
        moved, failed = await asyncio.to_thread(self.gallery.trash, ids)
        return web.json_response({"moved": moved, "failed": failed})

    async def desk_gallery_open(self, request):
        body = await request.json()
        e = self.gallery.get(str(body.get("id")))
        if e is None:
            raise web.HTTPNotFound()
        reveal(Path(os.path.dirname(e.path)) if body.get("folder") else Path(e.path))
        return web.json_response({"ok": True})

    async def desk_gallery_send(self, request):
        """Offers gallery files to the phone straight from where they are (nothing is copied)."""
        body = await request.json()
        to = self.target(body.get("to"))
        sent = 0
        for eid in [str(i) for i in body.get("ids", [])][:500]:
            e = self.gallery.get(eid)
            if e is None or not os.path.exists(e.path):
                continue
            mime = mimetypes.guess_type(e.name)[0] or "application/octet-stream"
            await self.publish(new_item("file", "laptop", name=e.name, size=e.size, mime=mime, path=e.path, **self.tag(to)))
            sent += 1
        return web.json_response({"sent": sent})

    async def desk_gallery_folders(self, request):
        g = self.gallery
        if request.method == "POST":
            body = await request.json()
            if body.get("remove"):
                g.remove_folder(str(body["remove"]))
            path = body.get("add")
            if body.get("pick"):
                path = await asyncio.to_thread(tx.pick_folder, "Choose a folder to show in the Gallery")
                if path is None:
                    return web.json_response({"folders": g.folder_list(), "picker": False}, status=501)
            if path:
                p = Path(str(path)).expanduser()
                if not p.is_dir():
                    raise web.HTTPBadRequest(text="That isn't a folder.")
                g.add_folder(str(p))
            await self.rescan_gallery()
        return web.json_response({"folders": g.folder_list()})

    # ---- updates ---------------------------------------------------------- #
    def update_info(self) -> dict:
        return {"current": VERSION, "latest": self.latest, "available": up.newer(self.latest, VERSION),
                "kind": up.kind(), "auto": bool(self.config.get("update_check", True)), "busy": self.updating}

    async def check_update(self) -> dict:
        latest = await asyncio.to_thread(up.latest_version)
        if latest:
            self.latest = latest
        info = self.update_info()
        info["online"] = latest is not None
        await self.desk_send({"type": "update", **info})
        return info

    async def version_watcher(self) -> None:
        """After the app is reinstalled or updated by hand, the old program would keep running
        with the new pages (and their new buttons would fail). Notice that and restart."""
        path = Path(__file__).resolve().parent / "VERSION"
        while True:
            await asyncio.sleep(5)
            try:
                on_disk = path.read_text().strip()
            except OSError:
                continue
            if on_disk and on_disk != VERSION and not self.updating:
                busy = self.downloads or any(not i.done for i in self.uploads.values())
                if busy:
                    continue
                print(f"Tonefer {on_disk} was installed; restarting (was {VERSION})", flush=True)
                await self.desk_send({"type": "updating", "stage": "restart", "version": on_disk})
                await asyncio.sleep(0.5)
                up.restart()

    async def update_watcher(self) -> None:
        """Looks for a new version shortly after start and twice a day, if allowed."""
        await asyncio.sleep(20)
        while True:
            if self.config.get("update_check", True):
                try:
                    await self.check_update()
                except Exception:
                    pass
            await asyncio.sleep(12 * 3600)

    async def desk_update_get(self, request):
        if request.query.get("check"):
            return web.json_response(await self.check_update())
        return web.json_response(self.update_info())

    async def desk_update_set(self, request):
        body = await request.json()
        self.config.set(update_check=bool(body.get("auto")))
        return web.json_response(self.update_info())

    async def desk_update_run(self, request):
        """Downloads the new version, installs it over this one and restarts."""
        if self.updating:
            raise web.HTTPConflict(text="An update is already running.")
        if any(not i.done for i in self.uploads.values()) or self.downloads:
            raise web.HTTPConflict(text="A transfer is in progress. Update when it has finished.")
        info = await self.check_update()
        if not info["available"]:
            raise web.HTTPBadRequest(text="You already have the newest version." if info.get("online")
                                     else "Can't reach GitHub. Connect the laptop to the internet and try again.")
        kind = info["kind"]
        if kind == "manual":
            raise web.HTTPBadRequest(text="This copy wasn't installed from the app package. Download the new version from GitHub.")
        self.updating = True
        loop = asyncio.get_running_loop()

        def say(stage: str, **extra) -> None:
            event = {"type": "updating", "stage": stage, "version": self.latest, **extra}
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.desk_send(event)))

        try:
            folder = APP_DIR / "update"
            if kind == "git":
                ok, msg = await asyncio.to_thread(up.git_pull)
            else:
                url, name = (up.EXE_URL, "ToneferSetup.exe") if kind == "windows" else (up.DEB_URL, "tonefer.deb")
                say("download", done=0, total=0)
                await asyncio.to_thread(up.download, url, folder / name, lambda d, t: say("download", done=d, total=t))
                say("install")
                if kind == "windows":
                    await asyncio.to_thread(up.run_windows_installer, folder / name)
                    ok, msg = True, "Installing"
                else:
                    ok, msg = await asyncio.to_thread(up.install_deb, folder / name)
            if not ok:
                say("failed", message=msg)
                raise web.HTTPBadRequest(text=msg)
            say("restart")
            await asyncio.sleep(0.8)
            if kind == "windows":
                loop.call_later(0.5, os._exit, 0)   # the installer replaces the files and reopens Tonefer
            else:
                loop.call_later(0.5, up.restart)
            return web.json_response({"ok": True, "version": self.latest})
        except web.HTTPException:
            raise
        except Exception as e:
            say("failed", message=str(e))
            raise web.HTTPBadRequest(text=f"Update failed: {e}")
        finally:
            self.updating = False

    # ---- guest sessions --------------------------------------------------- #
    def guest_qr(self, g: Guest, ip: str) -> dict:
        url = f"http://{ip}:{PORT}/#k={g.key_b64}" if ip else ""
        svg = ""
        if url:
            img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
            svg = img.to_string(encoding="unicode")
        return {"id": g.id, "name": g.name, "expires": int(g.expires * 1000), "url": url, "svg": svg,
                "online": list(self.phones.values()).count(g.id)}

    async def desk_guest_start(self, request):
        body = await request.json() if request.can_read_body else {}
        name = " ".join(str((body or {}).get("name") or "").split())[:30] or f"Guest {len(self.guests) + 1}"
        g = Guest(name)
        self.guests[g.id] = g
        self.save_guests()
        await self.announce_presence()
        return await self.desk_guest_show(request, g.id)

    async def desk_guest_show(self, request, gid: str | None = None):
        g = self.guests.get(gid or request.match_info["id"])
        if g is None:
            raise web.HTTPNotFound(text="That guest session has ended.")
        ips = [d["ip"] for d in await asyncio.to_thread(netinfo.addresses)]
        chosen = request.query.get("ip")
        if chosen not in ips:
            chosen = ips[0] if ips else ""
        return web.json_response(self.guest_qr(g, chosen))

    async def end_guest(self, gid: str) -> None:
        if self.guests.pop(gid, None) is None:
            return
        self.save_guests()
        for ws, s in list(self.phones.items()):
            if s == gid:
                self.phones.pop(ws, None)
                await ws.close(code=4001, message=b"session ended")
        await self.announce_presence()

    async def desk_guest_end(self, request):
        await self.end_guest(request.match_info["id"])
        return web.json_response({"ok": True})

    # ---- where received files are saved ----------------------------------- #
    def save_info(self) -> dict:
        return {"dir": str(self.recv_dir()), "custom": bool(self.config.get("received_dir")),
                "ask": bool(self.config.get("ask_save", False))}

    async def desk_save_get(self, request):
        return web.json_response(self.save_info())

    async def desk_save_set(self, request):
        body = await request.json()
        if "ask" in body:
            self.config.set(ask_save=bool(body["ask"]))
        if body.get("reset"):
            self.config.set(received_dir="")
        path = body.get("dir")
        if body.get("pick"):
            path = await asyncio.to_thread(tx.pick_folder, "Choose where Tonefer saves what your phone sends")
            if path is None:
                return web.json_response({**self.save_info(), "picker": False}, status=501)
        if path:
            dest = Path(path).expanduser()
            if not dest.is_dir() or not os.access(dest, os.W_OK):
                raise web.HTTPBadRequest(text="Tonefer can't write to that folder.")
            self.config.set(received_dir=str(dest))
        return web.json_response(self.save_info())

    async def desk_move(self, request):
        """Moves one received file to a folder you pick (the "ask where to save" flow)."""
        item = self.history.get(request.match_info["id"])
        if not item or item["kind"] != "file":
            raise web.HTTPNotFound()
        src = FILES_DIR / item["path"]
        if not src.exists():
            raise web.HTTPGone(text="The file was moved or deleted.")
        body = await request.json() if request.can_read_body else {}
        path = (body or {}).get("dir")
        if not path:
            path = await asyncio.to_thread(tx.pick_folder, f"Save {item['name']} to…")
            if path is None:
                return web.json_response({"picker": False}, status=501)
            if not path:
                return web.json_response({"cancelled": True})
        folder = Path(path).expanduser()
        if not folder.is_dir() or not os.access(folder, os.W_OK):
            raise web.HTTPBadRequest(text="Tonefer can't write to that folder.")
        dest = unique_path(folder, src.name)
        await asyncio.to_thread(shutil.move, str(src), dest)
        item["path"] = self.rel(dest)
        item["name"] = dest.name
        self.history.save()
        return web.json_response({"ok": True, "dir": str(folder), "name": dest.name})

    async def desk_extract(self, request):
        item = self.history.get(request.match_info["id"])
        if not item or item["kind"] != "file" or not item["name"].lower().endswith(".zip"):
            raise web.HTTPNotFound()
        path = FILES_DIR / item["path"]
        if not path.exists():
            raise web.HTTPGone(text="The zip was moved or deleted.")
        try:
            target = await asyncio.to_thread(tx.extract_zip, path)
        except (OSError, ValueError, __import__("zipfile").BadZipFile) as e:
            raise web.HTTPBadRequest(text=f"Couldn't unzip: {e}")
        reveal(target)
        return web.json_response({"path": str(target), "name": target.name})

    async def desk_file(self, request):
        item = self.history.get(request.match_info["id"])
        if not item or item["kind"] != "file":
            raise web.HTTPNotFound()
        path = FILES_DIR / item["path"]
        if not path.exists():
            raise web.HTTPGone(text="File was moved or deleted.")
        disp = "attachment" if request.query.get("download") else "inline"
        return web.FileResponse(path, headers={
            "Content-Type": item.get("mime") or "application/octet-stream",
            "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(item['name'])}"})

    async def desk_pair(self, request):
        addrs = await asyncio.to_thread(netinfo.addresses)
        ips = [d["ip"] for d in addrs]
        chosen = request.query.get("ip")
        if chosen not in ips:
            chosen = ips[0] if ips else ""
        url = f"http://{chosen}:{PORT}/#k={self.vault.key_b64}" if chosen else ""
        svg = ""
        if url:
            img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
            svg = img.to_string(encoding="unicode")
        now = time.monotonic()
        if now - self._net_checked > 20:
            self._net_cache = {
                "wifi": await asyncio.to_thread(netinfo.wifi_name),
                "firewall": await asyncio.to_thread(netinfo.firewall_hint, PORT),
            }
            self._net_checked = now
        return web.json_response({"addrs": addrs, "ip": chosen, "url": url, "svg": svg,
                                  "address": f"{chosen}:{PORT}" if chosen else "",
                                  "phones": len(self.phones), **self._net_cache})

    async def desk_speedtest(self, request):
        if not self.phones:
            raise web.HTTPConflict(text="Connect a phone first.")
        await self.to_phones({"type": "speedtest", "bytes": SPEEDTEST_BYTES}, None)
        return web.json_response({"ok": True, "bytes": SPEEDTEST_BYTES})

    async def desk_hotspot_get(self, request):
        saved = await asyncio.to_thread(netinfo.saved_wifi)
        current = await asyncio.to_thread(netinfo.wifi_name)
        return web.json_response({"name": self.config.get("hotspot", ""), "enabled": self.config.get("auto_join", True),
                                  "saved": saved, "current": current, "status": self.hotspot_status,
                                  "platform": sys.platform})

    async def desk_hotspot_set(self, request):
        body = await request.json()
        self.config.set(hotspot=str(body.get("name", "")).strip(), auto_join=bool(body.get("enabled", True)))
        self.hotspot_status = ""
        return await self.desk_hotspot_get(request)

    async def hotspot_watcher(self) -> None:
        """Every few seconds: if the chosen hotspot is in range and we're not on it, join it."""
        rounds = 0
        while True:
            await asyncio.sleep(6)
            rounds += 1
            name = self.config.get("hotspot", "")
            if not name or not self.config.get("auto_join", True):
                continue
            try:
                current = await asyncio.to_thread(netinfo.wifi_name)
                if current == name:
                    self.hotspot_status = f"Connected to {name}"
                    continue
                visible = await asyncio.to_thread(netinfo.visible_wifi, rounds % 3 == 0)
                if name not in visible:
                    self.hotspot_status = f"Waiting for {name} to appear"
                    continue
                self.hotspot_status = f"Joining {name}…"
                ok = await asyncio.to_thread(netinfo.join_wifi, name)
                self.hotspot_status = f"Connected to {name}" if ok else f"Couldn't join {name}"
                if ok:
                    await self.desk_send({"type": "notice", "text": f"Joined hotspot {name}"})
            except Exception as e:  # never let the watcher die
                self.hotspot_status = f"Auto-join error: {e}"

    async def desk_repair(self, request):
        self.vault.rotate()
        for ws in list(self.phones):
            await ws.close(code=4001, message=b"unpaired")
        self.phones.clear()
        self.guests.clear()
        self.save_guests()
        await self.announce_presence()
        return web.json_response({"ok": True})

    async def desk_delete(self, request):
        item = self.history.remove(request.match_info["id"])
        if item:
            await self.broadcast({"type": "deleted", "id": item["id"]})
        return web.json_response({"ok": True})

    async def desk_clear(self, request):
        self.history.clear()
        await self.broadcast({"type": "cleared"})
        return web.json_response({"ok": True})

    async def desk_open_folder(self, request):
        reveal(FILES_DIR)
        return web.json_response({"path": str(FILES_DIR)})

    # ---- wiring --------------------------------------------------------- #
    def build(self) -> web.Application:
        app = web.Application(middlewares=[self.guard], client_max_size=MAX_FILE + 1024 * 1024)
        r = app.router
        r.add_get("/", self.phone_index)
        r.add_get("/ws", self.phone_ws)
        r.add_get("/api/ping", self.phone_ping)
        r.add_post("/api/upload", self.phone_upload)
        r.add_get("/api/speedtest", self.phone_speed_down)
        r.add_post("/api/speedtest", self.phone_speed_up)
        r.add_get("/api/file/{id}", self.phone_file)
        r.add_post("/api/zip/start", self.phone_zip_start)
        r.add_post("/api/zip/{zid}/finish", self.phone_zip_finish)
        r.add_delete("/api/zip/{zid}", self.phone_zip_cancel)
        r.add_post("/api/upload/start", self.phone_upload_start)
        r.add_get("/api/upload/{tid}", self.phone_upload_state)
        r.add_post("/api/upload/{tid}/{index}", self.phone_upload_chunk)
        r.add_delete("/api/upload/{tid}", self.phone_upload_cancel)
        r.add_get("/desk", self.desk_index)
        r.add_get("/desk/ws", self.desk_ws)
        r.add_post("/desk/api/text", self.desk_text)
        r.add_post("/desk/api/upload", self.desk_upload)
        r.add_get("/desk/file/{id}", self.desk_file)
        r.add_get("/desk/api/pair", self.desk_pair)
        r.add_post("/desk/api/repair", self.desk_repair)
        r.add_post("/desk/api/speedtest", self.desk_speedtest)
        r.add_get("/desk/api/hotspot", self.desk_hotspot_get)
        r.add_post("/desk/api/hotspot", self.desk_hotspot_set)
        r.add_post("/desk/api/delete/{id}", self.desk_delete)
        r.add_post("/desk/api/clear", self.desk_clear)
        r.add_post("/desk/api/open-folder", self.desk_open_folder)
        r.add_post("/desk/api/send-folder", self.desk_send_folder)
        r.add_post("/desk/api/extract/{id}", self.desk_extract)
        r.add_get("/desk/api/gallery", self.desk_gallery)
        r.add_get("/desk/api/gallery/status", self.desk_gallery_status)
        r.add_get("/desk/thumb/{id}", self.desk_thumb)
        r.add_get("/desk/media/{id}", self.desk_media)
        r.add_post("/desk/api/gallery/trash", self.desk_gallery_trash)
        r.add_post("/desk/api/gallery/open", self.desk_gallery_open)
        r.add_post("/desk/api/gallery/send", self.desk_gallery_send)
        r.add_get("/desk/api/gallery/folders", self.desk_gallery_folders)
        r.add_post("/desk/api/gallery/folders", self.desk_gallery_folders)
        r.add_get("/desk/api/update", self.desk_update_get)
        r.add_post("/desk/api/update", self.desk_update_run)
        r.add_post("/desk/api/update/auto", self.desk_update_set)
        r.add_post("/desk/api/guest", self.desk_guest_start)
        r.add_get("/desk/api/guest/{id}", self.desk_guest_show)
        r.add_post("/desk/api/guest/{id}/end", self.desk_guest_end)
        r.add_get("/desk/api/save-location", self.desk_save_get)
        r.add_post("/desk/api/save-location", self.desk_save_set)
        r.add_post("/desk/api/move/{id}", self.desk_move)
        r.add_static("/static", WEB / "static")

        async def start_watcher(_app):
            _app["watcher"] = asyncio.create_task(self.hotspot_watcher())
            _app["janitor"] = asyncio.create_task(self.janitor())
            _app["awake"] = asyncio.create_task(self.stay_awake())
            _app["updates"] = asyncio.create_task(self.update_watcher())
            _app["version"] = asyncio.create_task(self.version_watcher())

        async def stop_watcher(_app):
            _app["watcher"].cancel()
            _app["janitor"].cancel()
            _app["awake"].cancel()
            _app["updates"].cancel()
            _app["version"].cancel()

        app.on_startup.append(start_watcher)
        app.on_cleanup.append(stop_watcher)
        return app


def reveal(target: Path) -> None:
    """Opens a folder in the system file manager."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        elif shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", str(target)])
    except Exception:
        pass


def secrets_equal(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


def quote(s: str) -> str:
    from urllib.parse import quote as q
    return q(s)


def main() -> None:
    if "--doctor" in sys.argv:
        netinfo.doctor(PORT)
        return
    tonefer = Tonefer()
    app = tonefer.build()
    desk_url = f"http://127.0.0.1:{PORT}/desk"
    addrs = netinfo.addresses()
    print(f"\n  tonefer {VERSION}  ·  developed & owned by K S Pankaj")
    print(f"  laptop view  {desk_url}")
    for d in addrs:
        print(f"  phone reach  http://{d['ip']}:{PORT}   ({d['iface']})")
    if not addrs:
        print("  no network yet: turn on your phone's hotspot and join it from this laptop")
    fw = netinfo.firewall_hint(PORT)
    if fw and fw["name"] in ("ufw", "firewalld", "windows-public"):
        print(f"\n  ! {fw['text']}\n    fix: {fw['fix']}")
    print(f"  files        {FILES_DIR}\n")
    if "--no-browser" not in sys.argv:
        app.on_startup.append(lambda _: _open_later(desk_url))
    try:
        web.run_app(app, host="0.0.0.0", port=PORT, print=None)
    except OSError as e:
        if getattr(e, "errno", None) in (98, 48, 10048):
            print(f"  Port {PORT} is busy — tonefer is probably already running.")
            print(f"  Open {desk_url} or set TONEFER_PORT to another number.")
            sys.exit(1)
        raise


async def _open_later(url: str) -> None:
    async def go():
        await asyncio.sleep(0.6)
        webbrowser.open(url)
    asyncio.get_running_loop().create_task(go())


if __name__ == "__main__":
    main()
