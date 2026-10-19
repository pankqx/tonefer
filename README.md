# tonefer

Send photos, files and messages between your phone and laptop — privately, with no internet and no cloud.

- **Works without Wi‑Fi.** Turn on your phone's hotspot and connect the laptop to it. The two devices talk directly over that link. Local transfers don't use mobile data.
- **End-to-end encrypted.** Pairing is a one-time QR scan that shares a 256-bit key. Every message and file is sealed with it (XSalsa20‑Poly1305). Anything that doesn't decrypt is rejected.
- **Keeps history.** Everything you send either way stays in a timeline on both devices. Files land in `~/Tonefer/Received` and `~/Tonefer/Sent`.
- **Minimal.** One timeline, one composer, drag‑and‑drop, paste.

## Run it

Ubuntu / Linux:

```bash
./run.sh
```

Windows: double-click `run.bat`. Allow it through the firewall on **private** networks when Windows asks.

The first run creates a virtual environment and installs four packages (`aiohttp`, `pynacl`, `qrcode`, `psutil`). The laptop view then opens in your browser at `http://127.0.0.1:8765/desk`.

## Pair your phone (once)

1. Turn on **Hotspot** on your phone.
2. Connect the laptop to that hotspot.
3. Scan the QR code shown in the laptop view with your phone camera.
4. In Chrome's menu, tap **Add to Home screen** so tonefer opens like an app.

From then on: start tonefer on the laptop, open it on the phone, done.

If the laptop gets a different address on the hotspot later, just scan again. To revoke every phone, use **Unpair all phones**.

## How it's built

```
server.py          laptop app (Python, aiohttp)
web/desk/          laptop view    — served on 127.0.0.1 only
web/phone/         phone view     — served on the local network
web/static/        shared css/js, tweetnacl (vendored, works offline)
docs/PROTOCOL.md   wire format, for the native Android app
```

Settings via environment variables: `TONEFER_PORT` (default 8765), `TONEFER_FILES` (default `~/Tonefer`) and `TONEFER_HOME` (default `~/.tonefer`, holds the key and history).

## Security notes

- The pairing key travels in the QR link's `#fragment`, which browsers never send to servers. It is stored in `~/.tonefer/pairing.key` (mode 600) and in the phone browser's storage.
- The laptop view refuses any request that isn't from this machine. It also checks the `Host` header, which blocks DNS-rebinding.
- **Quick-start limitation:** the phone page's code is itself served over plain HTTP. Someone *already connected to your hotspot* could in theory tamper with it. Keep your hotspot password-protected. The native Android app (next milestone) removes this, because the code ships inside the app.

## Roadmap

- [x] Quick start: laptop app + phone web view, encrypted text, photos and files, history
- [ ] Native Android app: share-sheet target ("Share → tonefer"), background notifications, faster large files
- [ ] Windows packaging (single .exe)
- [ ] Clipboard sync (quick-settings tile)
