# Tonefer — User Guide

This guide takes you from download to everyday one-click use. No Git or programming knowledge is needed: copy each command and paste it into a terminal.

> **Where things run:** the Tonefer app runs on your **laptop**. Your **phone** uses either the Tonefer Android app or a page in Chrome. Nothing needs to be uploaded to the internet.

## Contents

1. [Requirements](#1-requirements)
2. [Install: Ubuntu app, Windows app, browser, Android](#2-install--choose-how-you-want-to-use-it)
3. [One-click setup (source install)](#3-one-click-setup-only-for-option-b)
4. [Pair your phone](#4-pair-your-phone)
5. [Everyday use](#5-everyday-use)
6. [Connection options, auto hotspot & speed](#6-connection-options)
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

## 2. Install — choose how you want to use it

Tonefer always runs on the laptop. Pick any of these; they all share the same pairing, history and files.

| Where | How | Best for |
|---|---|---|
| **Ubuntu app** | [tonefer.deb](https://github.com/pankqx/tonefer/releases/latest/download/tonefer.deb) | Everyday use on Ubuntu: own window, starts at login |
| **Windows app** | [ToneferSetup.exe](https://github.com/pankqx/tonefer/releases/latest/download/ToneferSetup.exe) | Everyday use on Windows 10/11: tray icon, starts at sign-in |
| **Laptop browser** | Any browser at `http://127.0.0.1:8765/desk` | People who'd rather not install an app window |
| **Android app** | [tonefer.apk](https://github.com/pankqx/tonefer-android/releases/latest/download/tonefer.apk) | The phone side (or use Chrome on the phone, no install) |

### Ubuntu app

1. Download **tonefer.deb**, double-click it and choose **Install** (or `sudo apt install ~/Downloads/tonefer.deb`).
2. Press <kbd>Super</kbd>, type **Tonefer**, open it. Right-click the dock icon → **Pin to Dash**.
3. Prefer your browser? Right-click the Tonefer icon → **Open in browser**.

Tonefer keeps running in the background when the window is closed, so photos still arrive. It starts at every login, and the firewall is opened during install.

> **Used `./run.sh` or the install script before?** Run `cd ~/tonefer && ./scripts/uninstall-ubuntu.sh` first so the two setups don't clash. Pairing and history are kept.

### Windows app

1. Download **ToneferSetup.exe** and run it. Keep **Start Tonefer when I sign in** ticked.
2. Open **Tonefer** from the Start menu. It opens in its own window, and a **Tonefer icon appears in the system tray** (bottom-right, near the clock).
3. The tray icon menu has **Open Tonefer**, **Open in browser**, **Start with Windows** (on/off) and **Quit Tonefer**.

The installer also adds a firewall rule so your phone can reach the PC. If Windows SmartScreen says *"Windows protected your PC"*, choose **More info → Run anyway**. That appears for new apps that aren't code-signed.

**No install?** Download **Tonefer-portable.zip**, extract it and run `Tonefer.exe`. Allow it on Private and Public networks when Windows Firewall asks.

### Laptop browser (no app window)

The browser version is the same Tonefer. While Tonefer is running on the laptop (Ubuntu app, Windows app, or `./run.sh`), open **http://127.0.0.1:8765/desk** in Chrome, Firefox, Edge or Brave and bookmark it.

Without installing anything, from source:

```bash
sudo apt install -y git python3 python3-venv
git clone https://github.com/pankqx/tonefer.git ~/tonefer
cd ~/tonefer && ./run.sh        # opens your browser automatically
```

On Windows from source: install Python 3, download the ZIP from GitHub, and double-click `run.bat`.

---

## 3. One-click setup (only when running from source on Ubuntu)

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
| **Phone hotspot** | Fast; best on 5 GHz | Settings → Hotspot → on. The laptop joins by itself (6a). |
| **Shared Wi‑Fi** | Depends on the network | Both devices on the same network. Some public or college networks block device-to-device traffic. |

**Tip:** in the phone's hotspot settings, choose the **5 GHz** band if it's offered. Photos transfer noticeably faster.

### 6a. Automatic hotspot connection

With this set up, sharing works even when the hotspot is off:

1. **Share → Tonefer** on the phone.
2. If the laptop can't be reached, Tonefer **keeps the item** and **opens the hotspot switch**. Tap it on.
3. The laptop sees the hotspot and **joins it by itself** within a few seconds.
4. Tonefer **delivers the item automatically** and confirms with a notification.

> Android doesn't allow apps to turn the hotspot on by themselves (blocked since Android 8). Tonefer opens the switch for you, so it's one tap. Even quicker: add the **Hotspot** tile to the phone's Quick Settings and swipe down.

**Ubuntu setup (once):**

1. Turn on the phone's hotspot and join it once from the laptop's Wi‑Fi menu, so the laptop knows the password.
2. Run:
   ```bash
   cd ~/tonefer
   ./scripts/install-ubuntu.sh --hotspot "Your Hotspot Name"
   ```
   Or, in Tonefer on the laptop (the only way with the app install), open the **Auto-join hotspot** window, pick the hotspot and leave the switch on.

From then on, Tonefer checks every few seconds. When the hotspot appears, the laptop joins it, even if it's connected to other Wi‑Fi.

**Windows setup (once):**

1. Turn on the phone's hotspot and join it from the Wi‑Fi menu (taskbar → Wi‑Fi icon).
2. Open **Settings → Network & internet → Wi‑Fi → Manage known networks → your hotspot**, then:
   - turn on **Connect automatically when in range**;
   - set **Network profile type** to **Private**.
3. In Tonefer on the laptop, open the **Auto-join hotspot** window, pick the hotspot and leave the switch on. Tonefer then switches to it from other Wi‑Fi too.
4. Make Tonefer start with Windows: press <kbd>Win+R</kbd>, type `shell:startup`, Enter, and put a shortcut to `run.bat` in that folder.

The same thing from the command line (Command Prompt, using your hotspot's name):

```bat
netsh wlan set profileparameter name="Your Hotspot Name" connectionmode=auto
netsh wlan connect name="Your Hotspot Name"
```

### 6b. Transfer speed

The **Transfer speed** window on the laptop shows the real speed of every transfer, measured live while the bytes cross the network. **Run speed test** sends 16 MB each way to the connected phone. Typical results: hotspot 3–20 MB/s, USB tethering 15–40 MB/s.

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

- **Ubuntu app:** install the newest **tonefer.deb** over the old one.
- **Windows app:** run the newest **ToneferSetup.exe**. It replaces the old version.
- **Android:** install the newest **tonefer.apk** over the old one.
- **From source:** `cd ~/tonefer && git pull`

Settings, pairing and history are always kept.

---

## 9. Windows

Install **ToneferSetup.exe** (section 2). Then:

1. Join your phone's hotspot once. In **Settings → Network & internet → Wi‑Fi → Manage known networks → your hotspot**, turn on **Connect automatically when in range**.
2. In Tonefer, open the **Auto-join hotspot** window and pick the hotspot.

The installer handles the firewall rule and start-up.

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

- **Ubuntu app:** `sudo apt remove tonefer` (or remove it in App Center).
- **Windows app:** Settings → Apps → Installed apps → Tonefer → Uninstall.
- **Source setup:** `cd ~/tonefer && ./scripts/uninstall-ubuntu.sh`

Your files (`~/Tonefer`) and pairing (`~/.tonefer`) are kept. Delete those folders to remove everything.

---

## 12. Privacy and security

- **Local only:** no servers, accounts, analytics or cloud. Data moves directly between your two devices.
- **End-to-end encrypted:** every message and file is sealed with XSalsa20‑Poly1305 using a 256‑bit key that is shared only through the QR code.
- **Laptop window is private:** it only opens on the laptop itself, so other devices can't reach it.
- **Revocable:** *Unpair all phones* replaces the key immediately.
