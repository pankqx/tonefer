# Tonefer — User Guide

This guide takes you from download to everyday one-click use. No Git or programming knowledge is needed: copy each command and paste it into a terminal.

> **Where things run:** the Tonefer app runs on your **laptop**. Your **phone** uses either the Tonefer Android app or a page in Chrome. Nothing needs to be uploaded to the internet.

## Contents

1. [Requirements](#1-requirements)
2. [Install on Ubuntu](#2-install-on-ubuntu)
3. [One-click setup (recommended)](#3-one-click-setup-recommended)
4. [Pair your phone](#4-pair-your-phone)
5. [Everyday use](#5-everyday-use)
6. [Connection options](#6-connection-options)
7. [Android app](#7-android-app)
8. [Updating](#8-updating)
9. [Windows](#9-windows)
10. [Troubleshooting](#10-troubleshooting)
11. [Uninstall](#11-uninstall)
12. [Privacy and security](#12-privacy-and-security)

---

## 1. Requirements

| | |
|---|---|
| Laptop | Ubuntu 22.04 or newer (Windows 10/11 also supported) |
| Phone | Android 10 or newer for the app (any Android with Chrome for the web view) |
| Connection | Phone hotspot, USB cable, or any shared Wi‑Fi. Internet is **not** needed. |

---

## 2. Install on Ubuntu

Open a terminal (**Ctrl + Alt + T**) and run:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
git clone https://github.com/pankqx/tonefer.git ~/tonefer
```

<details>
<summary>Prefer not to use Git? Download the ZIP instead.</summary>

1. Open **github.com/pankqx/tonefer**.
2. Click **Code → Download ZIP**.
3. Extract it into your home folder and rename the folder to `tonefer`.

</details>

---

## 3. One-click setup (recommended)

Run this **once**:

```bash
cd ~/tonefer
./scripts/install-ubuntu.sh
```

To have the laptop also join your phone's hotspot by itself, add its name. Join the hotspot once from the Wi‑Fi menu first.

```bash
./scripts/install-ubuntu.sh --hotspot "Your Hotspot Name"
```

The installer sets up five things, and each can be undone (see section 11):

| | What it does | Why it helps |
|---|---|---|
| 1 | Creates a private Python environment | Keeps Tonefer separate from the rest of the system |
| 2 | Runs Tonefer in the background at every login | No terminal, nothing to start by hand |
| 3 | Adds **Tonefer** to the app launcher | Press <kbd>Super</kbd>, type *Tonefer*, Enter. It opens in its own window. |
| 4 | Opens the firewall port (8765), if the firewall is on | Prevents *"This site can't be reached"* on the phone |
| 5 | Optional: auto-joins your phone's hotspot, ahead of other Wi‑Fi | Turning the hotspot on is the only step left |

<details>
<summary>Prefer to do these steps by hand?</summary>

```bash
# Start manually (keep the terminal open)
cd ~/tonefer && ./run.sh

# Open the firewall port
sudo ufw allow 8765/tcp

# Make the laptop auto-join your hotspot, ahead of other networks
nmcli connection modify "Your Hotspot Name" connection.autoconnect yes connection.autoconnect-priority 50
```
</details>

---

## 4. Pair your phone

You only do this once per phone.

1. Connect the phone and laptop (section 6). The phone hotspot is the simplest way.
2. Open Tonefer on the laptop. The **Pair a phone** window shows a QR code and confirms which network the laptop is on.
3. Pair the phone in one of these ways:
   - **Android app:** open it and tap **Scan pairing code**.
   - **Chrome:** point the camera at the code and open the link. Then choose ⋮ → **Add to Home screen**.

If scanning fails, type the address shown under the QR code (for example `10.42.0.15:8765`) into Chrome.

---

## 5. Everyday use

After the one-click setup, a session takes **two taps**:

1. Turn on the phone's hotspot. The laptop joins it by itself.
2. Open Tonefer on the phone.

| Task | Laptop | Phone |
|---|---|---|
| Send a note | Type, press <kbd>Enter</kbd> | Type, tap ↑ |
| Send photos or files | Drag onto the window, <kbd>Ctrl+V</kbd>, or **+** | **+**, or *Share → Tonefer* in any app (Android app) |
| Copy a received note | Copy icon | Copy icon, or automatic (app setting) |
| Save a received photo | Click it, then **Save** | Tap it, then **Save**, or automatic (app setting) |
| Find received files | Tools → **Open Tonefer folder** | Pictures/Tonefer or Downloads |
| Read these instructions | **Instructions** tab or <kbd>F1</kbd> | **?** button |

Files sent to the laptop are saved in `~/Tonefer/Received`. History is kept on both devices until you clear it.

---

## 6. Connection options

| Option | Speed | How |
|---|---|---|
| **USB tethering** | Fastest and most stable | Plug the phone in, then Settings → Hotspot & tethering → **USB tethering** |
| **Phone hotspot** | Fast; best on 5 GHz | Settings → Hotspot → on, then join it from the laptop |
| **Shared Wi‑Fi** | Depends on the network | Both devices on the same network. Some public or college networks block device-to-device traffic. |

**Tip:** in the phone's hotspot settings, choose the **5 GHz** band if it's offered. Photos transfer noticeably faster.

---

## 7. Android app

The Android app (repository **tonefer-android**) adds:

- **Share → Tonefer** from Gallery, Files or any app
- **Automatic discovery:** finds the laptop even when its address changes
- **Background connection** with notifications
- **Customisation:** theme, text size, auto-save photos, auto-copy notes, image quality, notifications

**Install:** on the phone, open **https://github.com/pankqx/tonefer-android/releases/latest/download/tonefer.apk**, then open the downloaded file. Allow *Install unknown apps* for your browser when asked.

---

## 8. Updating

```bash
cd ~/tonefer
git pull
systemctl --user restart tonefer   # only if you ran the one-click setup
```

If you used the ZIP, download it again and replace the folder. History and pairing are kept, because they live in `~/.tonefer`.

---

## 9. Windows

1. Install Python 3 from **python.org**, ticking **Add Python to PATH**.
2. Download the ZIP (section 2) and extract it.
3. Double-click **`run.bat`**. When Windows Firewall asks, allow **Private networks**.
4. Set the hotspot to Private: Settings → Network & internet → Wi‑Fi → *your hotspot* → **Private network**.
5. To start Tonefer with Windows: press <kbd>Win+R</kbd>, type `shell:startup`, and put a shortcut to `run.bat` in that folder.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| Phone shows *"This site can't be reached"* | Make sure the laptop is on the phone's hotspot. Then run `sudo ufw allow 8765/tcp`. |
| QR code scans but the page is blank | Check that Tonefer is running: `systemctl --user status tonefer`, or start it with `./run.sh`. |
| Phone shows **Unpaired** | Someone used *Unpair all phones*. Scan the new code. |
| Slow transfers | Use USB tethering or a 5 GHz hotspot, and keep the devices close. |
| Anything else | Run `cd ~/tonefer && ./run.sh doctor`. It lists addresses, the network and any firewall issues. |

To see the background service's log: `journalctl --user -u tonefer -n 50`

---

## 11. Uninstall

```bash
cd ~/tonefer
./scripts/uninstall-ubuntu.sh
```

This removes the background service and launcher. Your files (`~/Tonefer`) and pairing (`~/.tonefer`) are kept. Delete those folders to remove everything.

---

## 12. Privacy and security

- **Local only:** no servers, accounts, analytics or cloud. Data moves directly between your two devices.
- **End-to-end encrypted:** every message and file is sealed with XSalsa20‑Poly1305 using a 256‑bit key that is shared only through the QR code.
- **Laptop window is private:** it only opens on the laptop itself, so other devices can't reach it.
- **Revocable:** *Unpair all phones* replaces the key immediately.
