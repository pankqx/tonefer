# AGENTS.md

Instructions for AI coding agents working in this repo.
Humans: read [GUIDE.md](GUIDE.md). It explains everything from zero.

## What this project is

tonefer sends text, photos and files between a phone and a laptop over the phone's hotspot (no internet,
no cloud), end-to-end encrypted with a key shared once by QR code. The laptop runs a **Python aiohttp**
server; the phone uses a **vanilla JS** web page with **tweetnacl** for encryption (PyNaCl on the server,
both NaCl `secretbox` = XSalsa20-Poly1305).

## Layout

```
server.py              the whole backend: Vault (key + seal/open), History (history.json), Tonefer (routes, guard middleware, WebSockets)
web/desk/index.html    laptop UI, loopback only (/desk)
web/phone/index.html   phone UI, served on the LAN (/)
web/static/common.js   shared helpers: esc, linkify, size, toast, renderTimeline (window.T)
web/static/desk.js     laptop UI logic (plain JSON WebSocket, multipart upload, QR pairing panel)
web/static/phone.js    phone UI logic (pairing from #k=, seal/open, encrypted WebSocket + upload/download)
web/static/nacl-fast.min.js  vendored tweetnacl (do not edit)
docs/PROTOCOL.md       wire format; keep in sync with server.py and phone.js
run.sh / run.bat       create .venv, install requirements, start server
```

## Commands

```bash
./run.sh                    # Linux/macOS; opens http://127.0.0.1:8765/desk
./run.sh --no-browser
TONEFER_PORT=9000 TONEFER_HOME=/tmp/tf TONEFER_FILES=/tmp/tff ./run.sh   # isolated test run
```

No automated tests yet. If you add them, use `pytest` + `pytest-aiohttp` with `TONEFER_HOME`/`TONEFER_FILES` pointed at a temp dir.

## Security invariants (do not break)

- Every phone payload (WebSocket frames, upload body + meta header, downloaded files) is sealed with the vault key. Anything that fails to decrypt is rejected (`4001` close or `403`).
- `/desk*` is loopback-only AND requires a localhost `Host` header (DNS-rebinding defence).
- `/api*` and `/ws` need the token (`X-Tonefer-Token` or `?t=`), compared with `hmac.compare_digest`.
- The key travels only in the URL `#fragment` and is stored in `~/.tonefer/pairing.key` (mode 600).
- File names from clients go through `safe_name` + `unique_path`. Never write a client-supplied path directly.
- `History.public()` strips the local `path` field before anything is sent to a client.
- Any change to the wire format must update `docs/PROTOCOL.md`, `server.py` and `phone.js` together.

## Rules for agents

- Keep dependencies to the four in requirements.txt unless asked.
- Commit as `pankqx <pankqx@gmail.com>`. Do not add `Co-Authored-By` or any AI trailer.
- If you change behaviour, update GUIDE.md in the same PR.
