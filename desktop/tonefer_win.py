"""Tonefer for Windows.

One small program that:
  * runs the Tonefer server in the background (keeps receiving while windows are closed),
  * shows a tray icon (Open Tonefer · Open in browser · Start with Windows · Quit),
  * opens Tonefer in its own app window (Microsoft Edge app mode, built into Windows 10/11).

Start with --background to only run the server and tray (used at sign-in).
"""

from __future__ import annotations

import asyncio
import os
import time
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# Windowed builds have no console: send output and errors to a log file instead.
_LOG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Tonefer"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
if sys.stdout is None or sys.stderr is None:
    _log = open(_LOG_DIR / "tonefer.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log
print(f"--- Tonefer start {time.strftime('%Y-%m-%d %H:%M:%S') if 'time' in globals() else ''} args={sys.argv[1:]}")

import server  # noqa: E402  (the same server the Ubuntu app and browsers use)

PORT = server.PORT
URL = f"http://127.0.0.1:{PORT}/desk"
APP_NAME = "Tonefer"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Tonefer"


def server_up() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=0.6) as r:
            return r.status == 200
    except Exception:
        return False


def run_server() -> None:
    try:
        _serve()
    except Exception:
        import traceback
        traceback.print_exc()


def _serve() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def quiet(loop, ctx):
        # A phone leaving the hotspot resets its connection; that's normal, not an error.
        if isinstance(ctx.get("exception"), (ConnectionResetError, ConnectionAbortedError)):
            return
        loop.default_exception_handler(ctx)

    loop.set_exception_handler(quiet)
    from aiohttp import web
    app = server.Tonefer().build()
    runner = web.AppRunner(app, access_log=None)
    loop.run_until_complete(runner.setup())
    loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", PORT).start())
    loop.run_forever()


def find_edge() -> str | None:
    candidates = [
        shutil.which("msedge"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def open_window(*_) -> None:
    browser = find_edge()
    if not browser:
        webbrowser.open(URL)
        return
    profile = DATA / "window"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([browser, f"--app={URL}", "--window-size=1320,860", f"--user-data-dir={profile}",
                      "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"],
                     creationflags=0x08000000)  # no console window


def open_browser(*_) -> None:
    webbrowser.open(URL)


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --background')
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


def tray_image():
    """Teal circle with two arrows, drawn at runtime so no image files are needed."""
    from PIL import Image, ImageDraw
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, s - 2, s - 2), fill=(39, 149, 149, 255))
    c = (247, 246, 244, 255)
    d.line((16, 24, 46, 24), fill=c, width=5)
    d.polygon([(40, 16), (50, 24), (40, 32)], fill=c)
    d.line((18, 40, 48, 40), fill=c, width=5)
    d.polygon([(24, 32), (14, 40), (24, 48)], fill=c)
    return img


def run_tray() -> None:
    import pystray
    from pystray import Menu, MenuItem as Item

    def toggle(icon, item):
        set_autostart(not autostart_enabled())

    def quit_app(icon, item):
        icon.stop()
        os._exit(0)

    icon = pystray.Icon("tonefer", tray_image(), "Tonefer — running", menu=Menu(
        Item("Open Tonefer", open_window, default=True),
        Item("Open in browser", open_browser),
        Menu.SEPARATOR,
        Item("Start with Windows", toggle, checked=lambda item: autostart_enabled()),
        Menu.SEPARATOR,
        Item("Quit Tonefer", quit_app),
    ))
    icon.run()


def main() -> int:
    try:
        return _main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise


def _main() -> int:
    background = "--background" in sys.argv
    if server_up():
        # Already running (tray is up): just show the window.
        if not background:
            open_window()
        return 0
    threading.Thread(target=run_server, daemon=True, name="tonefer-server").start()
    for _ in range(50):
        if server_up():
            break
        time.sleep(0.1)
    if not background:
        open_window()
    run_tray()
    return 0


if __name__ == "__main__":
    sys.exit(main())
