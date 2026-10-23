#!/usr/bin/env python3
"""Tonefer for Ubuntu: opens Tonefer in its own app window.

Makes sure the background service is running (it keeps receiving when the
window is closed), then shows the laptop view in a native GTK + WebKit window.
Falls back to a browser app window if WebKitGTK isn't installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PORT = int(os.environ.get("TONEFER_PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}/desk"
HERE = Path(__file__).resolve().parent
SERVER = Path(os.environ.get("TONEFER_SERVER", HERE.parent / "server.py"))
APP_ID = "com.pankqx.Tonefer"

# WebKitGTK shows a blank window on some NVIDIA setups (e.g. many gaming laptops)
# with its DMA-BUF renderer; the fallback renderer is just as fast for this app.
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")


def server_up() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=0.6) as r:
            return r.status == 200
    except Exception:
        return False


def wait_up(seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if server_up():
            return True
        time.sleep(0.2)
    return False


def ensure_server() -> None:
    if server_up():
        return
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(["systemctl", "--user", "start", "tonefer.service"], capture_output=True)
        if wait_up(5):
            return
    # No service manager (or it failed): run the server ourselves, detached.
    log = Path.home() / ".tonefer" / "server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        subprocess.Popen([sys.executable, str(SERVER), "--no-browser"], stdout=out, stderr=out,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    wait_up(10)


def open_in_browser() -> None:
    for b in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"):
        if shutil.which(b):
            subprocess.Popen([b, f"--app={URL}", "--class=tonefer", "--window-size=1280,820"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
    webbrowser.open(URL)


def run_window() -> int:
    import gi
    gi.require_version("Gtk", "3.0")
    try:
        gi.require_version("WebKit2", "4.1")
    except ValueError:
        gi.require_version("WebKit2", "4.0")
    from gi.repository import Gio, GLib, Gtk, WebKit2

    GLib.set_prgname("tonefer")
    GLib.set_application_name("Tonefer")

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.window = None

        def do_activate(self):
            if self.window:
                self.window.present()
                return
            win = Gtk.ApplicationWindow(application=self, title="Tonefer")
            win.set_default_size(1320, 860)
            win.set_icon_name("tonefer")
            win.set_wmclass("tonefer", "Tonefer")

            ctx = WebKit2.WebContext.get_default()
            ctx.connect("download-started", self.on_download)
            view = WebKit2.WebView.new_with_context(ctx)
            s = view.get_settings()
            s.set_property("javascript-can-access-clipboard", True)
            s.set_property("enable-developer-extras", bool(os.environ.get("TONEFER_DEVTOOLS")))
            view.connect("decide-policy", self.on_policy)
            view.connect("load-failed", self.on_failed)
            view.load_uri(URL)
            win.add(view)

            quit_action = Gio.SimpleAction.new("quit", None)
            quit_action.connect("activate", lambda *_: self.quit())
            self.add_action(quit_action)
            self.set_accels_for_action("app.quit", ["<Control>q"])
            reload_action = Gio.SimpleAction.new("reload", None)
            reload_action.connect("activate", lambda *_: view.reload())
            self.add_action(reload_action)
            self.set_accels_for_action("app.reload", ["<Control>r", "F5"])

            win.show_all()
            self.window = win

        # Links in messages open in the normal browser, not inside the app.
        def on_policy(self, view, decision, kind):
            if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
                uri = decision.get_navigation_action().get_request().get_uri()
                if not uri.startswith(f"http://127.0.0.1:{PORT}") and not uri.startswith("about:"):
                    Gtk.show_uri_on_window(self.window, uri, Gtk.get_current_event_time())
                    decision.ignore()
                    return True
            return False

        # "Save" on a received file goes to ~/Downloads.
        def on_download(self, ctx, download):
            def decide(dl, suggested):
                folder = Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or Path.home() / "Downloads")
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / (suggested or "tonefer-file")
                n = 1
                while target.exists():
                    target = folder / f"{Path(suggested).stem} ({n}){Path(suggested).suffix}"
                    n += 1
                dl.set_destination(target.as_uri())
                return True
            download.connect("decide-destination", decide)
            download.connect("finished", lambda dl: self.notify_saved(dl))

        def notify_saved(self, dl):
            n = Gio.Notification.new("Saved to Downloads")
            n.set_body(Path(GLib.filename_from_uri(dl.get_destination())[0]).name)
            self.send_notification("saved", n)

        def on_failed(self, view, event, uri, error):
            # The service may still be starting; try again shortly.
            GLib.timeout_add_seconds(1, lambda: (view.load_uri(URL), False)[1])
            return True

    return App().run([sys.argv[0]])


def main() -> int:
    ensure_server()
    if "--background" in sys.argv:  # just make sure the service runs
        return 0
    if "--browser" in sys.argv:  # use the normal web browser instead of the app window
        webbrowser.open(URL)
        return 0
    try:
        return run_window()
    except (ImportError, ValueError) as e:
        print(f"WebKitGTK not available ({e}); opening in the browser instead.", file=sys.stderr)
        open_in_browser()
        return 0


if __name__ == "__main__":
    sys.exit(main())
