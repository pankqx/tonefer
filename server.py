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
MAX_FILE = 512 * 1024 * 1024  # 512 MB per transfer
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


# --------------------------------------------------------------------------- #
# Crypto
# --------------------------------------------------------------------------- #
class Vault:
    """Holds the pairing key. Rotating it unpairs every phone."""

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
        self.phones: set[web.WebSocketResponse] = set()
        self.desks: set[web.WebSocketResponse] = set()
        self._net_checked = -1e9
        self._net_cache: dict = {}
        self.config = Config(APP_DIR / "config.json")
        self.hotspot_status = ""

    # ---- broadcasting --------------------------------------------------- #
    async def broadcast(self, event: dict) -> None:
        for ws in list(self.desks):
            try:
                await ws.send_str(json.dumps(event))
            except Exception:
                self.desks.discard(ws)
        sealed = self.vault.seal_json(event)
        for ws in list(self.phones):
            try:
                await ws.send_str(sealed)
            except Exception:
                self.phones.discard(ws)

    async def desk_send(self, event: dict) -> None:
        msg = json.dumps(event)
        for ws in list(self.desks):
            try:
                await ws.send_str(msg)
            except Exception:
                self.desks.discard(ws)

    async def announce_presence(self) -> None:
        msg = json.dumps({"type": "presence", "phones": len(self.phones)})
        for ws in list(self.desks):
            try:
                await ws.send_str(msg)
            except Exception:
                self.desks.discard(ws)

    async def publish(self, item: dict) -> dict:
        self.history.add(item)
        await self.broadcast({"type": "item", "item": History.public(item)})
        return item

    def store_file(self, folder: str, name: str, data: bytes, mime: str | None, origin: str) -> dict:
        name = safe_name(name)
        dest = unique_path(FILES_DIR / folder, name)
        dest.write_bytes(data)
        mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return new_item("file", origin, name=dest.name, size=len(data), mime=mime,
                        path=str(dest.relative_to(FILES_DIR)))

    # ---- middleware ----------------------------------------------------- #
    @web.middleware
    async def guard(self, request: web.Request, handler):
        if request.path.startswith("/desk"):
            # Laptop UI: loopback only, and a localhost Host header
            # (blocks other devices and DNS-rebinding tricks).
            host = (request.host or "").rsplit(":", 1)[0]
            if request.remote not in ("127.0.0.1", "::1") or host not in LOCAL_HOSTS:
                raise web.HTTPForbidden(text="The laptop view is only available on this computer.")
        elif request.path.startswith("/api") or request.path == "/ws":
            token = request.headers.get("X-Tonefer-Token") or request.query.get("t", "")
            if not secrets_equal(token, self.vault.token):
                raise web.HTTPUnauthorized(text="Not paired. Scan the QR code on your laptop.")
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
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * 1024 * 1024)
        await ws.prepare(request)
        self.phones.add(ws)
        await self.announce_presence()
        await ws.send_str(self.vault.seal_json(
            {"type": "hello", "host": platform.node(), "items": self.history.public_list()}))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = self.vault.open_json(msg.data)
                except (nacl.exceptions.CryptoError, ValueError):
                    await ws.close(code=4001, message=b"bad key")
                    break
                if data.get("type") == "text":
                    text = str(data.get("text", ""))[:100_000]
                    if text.strip():
                        await self.publish(new_item("text", "phone", text=text))
        finally:
            self.phones.discard(ws)
            await self.announce_presence()
        return ws

    async def phone_ping(self, request):
        return web.json_response({"ok": True, "version": VERSION})

    async def phone_upload(self, request):
        if request.content_length and request.content_length > MAX_FILE + 1024:
            raise web.HTTPRequestEntityTooLarge(MAX_FILE, request.content_length)
        try:
            meta = self.vault.open_json(request.headers.get("X-Tonefer-Meta", ""))
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
            data = await asyncio.to_thread(self.vault.open, bytes(buf))
        except (nacl.exceptions.CryptoError, ValueError):
            raise web.HTTPForbidden(text="Payload did not decrypt. Re-pair your phone.")
        item = self.store_file("Received", name, data, meta.get("mime"), "phone")
        await self.publish(item)
        return web.json_response({"ok": True, "id": item["id"]})

    async def phone_file(self, request):
        item = self.history.get(request.match_info["id"])
        if not item or item["kind"] != "file":
            raise web.HTTPNotFound()
        path = FILES_DIR / item["path"]
        if not path.exists():
            raise web.HTTPGone(text="File was moved or deleted on the laptop.")
        data = await asyncio.to_thread(path.read_bytes)
        sealed = await asyncio.to_thread(self.vault.seal, data)
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

    # ---- laptop side ---------------------------------------------------- #
    async def desk_index(self, request):
        return web.FileResponse(WEB / "desk" / "index.html")

    async def desk_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.desks.add(ws)
        await ws.send_str(json.dumps({"type": "hello", "host": platform.node(),
                                      "items": self.history.public_list(),
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
        item = await self.publish(new_item("text", "laptop", text=text))
        return web.json_response(History.public(item))

    async def desk_upload(self, request):
        reader = await request.multipart()
        sent = []
        while (part := await reader.next()) is not None:
            if not part.filename:
                continue
            buf, size = BytesIO(), 0
            while chunk := await part.read_chunk(1 << 20):
                size += len(chunk)
                if size > MAX_FILE:
                    raise web.HTTPRequestEntityTooLarge(MAX_FILE, size)
                buf.write(chunk)
            mime = part.headers.get("Content-Type")
            item = self.store_file("Sent", part.filename, buf.getvalue(), mime, "laptop")
            await self.publish(item)
            sent.append(History.public(item))
        return web.json_response(sent)

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
        await self.broadcast_phones({"type": "speedtest", "bytes": SPEEDTEST_BYTES})
        return web.json_response({"ok": True, "bytes": SPEEDTEST_BYTES})

    async def broadcast_phones(self, event: dict) -> None:
        sealed = self.vault.seal_json(event)
        for ws in list(self.phones):
            try:
                await ws.send_str(sealed)
            except Exception:
                self.phones.discard(ws)

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
        target = str(FILES_DIR)
        try:
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            elif shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", target])
        except Exception:
            pass
        return web.json_response({"path": target})

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
        r.add_static("/static", WEB / "static")

        async def start_watcher(_app):
            _app["watcher"] = asyncio.create_task(self.hotspot_watcher())

        async def stop_watcher(_app):
            _app["watcher"].cancel()

        app.on_startup.append(start_watcher)
        app.on_cleanup.append(stop_watcher)
        return app


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
    print(f"\n  tonefer {VERSION}")
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
