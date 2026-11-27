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
| Send a folder | **+** → **Folder as zip**, or drag the folder onto the window | **+** → **Folder as zip** |
| Send several files as one zip | **+** → **Files as one zip** | **+** → **Files as one zip**, or the app setting *Share several files as one zip* |
| Unzip a received zip | Box icon on the zip | Open it with your Files app |
| Copy a received note | Copy icon | Copy icon, or automatic (app setting) |
| Choose where files are saved | Tools → **Change folder**, or tick **Ask where to save each file** | App setting *Ask where to save* |
| Find something old | Search box above the history | |
| Save a received photo | Click it, then **Save** | Tap it, then **Save**, or automatic (app setting) |
| Find received files | Tools → **Open Tonefer folder** | Pictures/Tonefer or Downloads |
| Read these instructions | **Instructions** tab or <kbd>F1</kbd> | **?** button |

**Folders and big files.** There is no size limit. Files travel in small encrypted pieces, so a multi-gigabyte video or a folder of thousands of photos works, and a piece lost to a hotspot hiccup is simply sent again. A folder is zipped as it travels, with its sub-folders kept. Photos and videos are stored in the zip as they are (they don't compress further); documents are compressed. In a phone *browser*, files you receive are assembled in the browser's memory, so for files over about 1 GB to the phone use the Android app.

**Guest sessions: a friend sends to your laptop.** In the laptop view open **Guest sessions**, type your friend's name and press **Start session**. Your friend joins the same hotspot and scans the code with their phone camera (no app needed). They get their own key: they see only what they and you exchange in that session, never your history, and their files land in `Received/Guest <name>`. A **Send to** switch appears above the message box so you can reply to them. Press **End session** to cut them off; sessions also end by themselves after 12 hours. Your own phone stays paired throughout.

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
- **Phone to phone:** a QR code that any other phone scans to swap files directly, no laptop

### Phone to phone (no laptop)

The Android app can connect two phones directly. The other phone needs no app: any camera and browser will do, iPhone included.

1. On the Android phone, turn on the **hotspot**, then open Tonefer → menu ⋮ → **Phone to phone** → **Start**. (Before pairing with a laptop, the button is on the welcome screen.)
2. On the other phone, **join that hotspot** in Wi‑Fi settings.
3. Point the other phone's **camera** at the code and tap the link. The Tonefer page opens and says *Connected*.

Now send notes, photos, files or a whole folder (as a zip) either way. What arrives on the Android phone can be opened or saved; photos save to `Pictures/Tonefer` if auto-save is on. Both phones on the same Wi‑Fi works too. **New code** in the menu cuts the other phone off; **Stop** ends it (it also stops by itself after 15 minutes with nobody connected). Nothing is kept after you stop, apart from what you saved.

If the page doesn't open: check the other phone is on the hotspot (not mobile data only), and if the screen lists two addresses, tap the other one so the code changes.

**Install:** on the phone, open **https://github.com/pankqx/tonefer-android/releases/latest/download/tonefer.apk**, then open the downloaded file. Allow *Install unknown apps* for your browser when asked.

---

## Gallery: your photos, videos and files

The **Gallery** tab in the laptop app (Ubuntu and Windows) shows every photo, video and file in your Pictures, Videos, Downloads, Desktop, Documents and Tonefer folders, newest first and grouped by day. Use **Folders → Add a folder** for anything else, such as an external drive.

- **View:** click a photo or video. Arrow keys or the scroll wheel go to the next one. Videos start playing at once; Space pauses.
- **Delete:** press Delete in the viewer, or press **Select**, pick several (Shift-click selects a range) and **Move to Trash**. Files go to the system Trash or Recycle Bin, so they can be restored.
- **Edit:** open a photo and press **Edit** (or <kbd>E</kbd>). Crop by dragging on the photo (Free, Original, 1:1, 4:3, 3:4, 16:9, 9:16), turn left or right, mirror or flip, and change light, contrast and colour. **Save as copy** keeps the original and writes `name (edited).jpg` next to it. **Replace original** puts the original in the Trash first, so it can always be restored. Edits are applied to the full-size photo and keep its date and camera details. Works for JPG, PNG, WebP and BMP.
- **Send:** **Send to phone** offers the file to your phone without copying it.
- **Files** lists documents, archives and music; clicking one opens it in its normal app.

Photos are placed on the day they were **taken**: Tonefer reads the date stored inside each photo (and inside phone videos), or the date in names like `IMG_20241005_143022.jpg`. The first scan reads every file once and shows a live scanner while it works; the dates are remembered in `~/.tonefer/gallery-dates.json`, so later scans take a moment.

Everything stays on the laptop. Thumbnails are cached in `~/.tonefer/thumbs`. Videos that the built-in player can't decode get an *Open in your video player* button; on Ubuntu, installing `gstreamer1.0-libav` lets most of them play inside Tonefer.

## Phone backup: every photo and video onto the laptop

The **Phone backup** tab copies everything off an Android phone over a USB cable in one go: Camera, Screenshots, WhatsApp (sent and received), Telegram, Instagram, Snapchat, Downloads, screen recordings, any other app folder and the memory card. You don't have to hunt through folders.

**Once, on the laptop (Ubuntu):** `sudo apt install adb`. On Windows, download *Android SDK Platform-Tools* from developer.android.com and unzip it to `C:\platform-tools`.

**Once, on the phone:**

1. **Settings → About phone** → tap **Build number** seven times.
2. **Settings → System → Developer options** → turn on **USB debugging**.
3. Connect the cable, unlock the phone and tap **Allow** (tick *Always allow from this computer*).

**Then:**

1. **Scan the phone.** You get a table of how many photos and videos are in each place, their size, and how many are already on the laptop.
2. Choose:
   - **Copy to laptop.** The phone isn't changed. Run it again later and only new photos are copied.
   - **Move to laptop (cut).** Each file is copied, then checked (same size and same MD5 checksum), and only then deleted from the phone. Anything that fails the check stays on the phone.
3. Watch the progress bar, speed and time left. **Stop** is safe: the next run carries on where it stopped.

Photos are saved in `~/Tonefer/Phone backup/<year>/<year>-<month>/` and appear in the Gallery straight away. **Change folder** puts them anywhere, such as an external drive (Tonefer checks there's enough space first). Two different photos with the same name are both kept (`name (2).jpg`). A list of every file, where it came from and where it went is kept in `Phone backup/.backup/manifest.csv`.

Hidden folders, such as WhatsApp's `.Statuses`, are skipped unless you tick *Include hidden folders*. App caches (`Android/data`) and the phone's own recycle bin are always skipped.

**Speed:** about 30–40 MB/s over USB, so roughly an hour for 100 GB. No cable? Android 11+ can use *Wireless debugging* (pair and connect in the same tab), but it's much slower.

On Android, open the menu → **Gallery** for the same timeline of the phone's photos and videos. Tap one to open the reels-style viewer: swipe up for the next, videos play as soon as they appear. The **Files** tab lists documents, archives, music and APKs once you allow *All files access*. Deleted items go to the system trash.

---

## 8. Updating

**Laptop app.** Tonefer looks for a new version when it starts and every few hours (this needs internet). When it finds one, it downloads and installs it by itself as soon as nothing is being transferred, then restarts on the new version. No password is needed: updates go into your home folder (`~/.local/share/tonefer`), and the installed app hands over to the newest copy when it starts. **Tools → Check for updates** does the same on demand. To stop automatic installs, untick **Install updates automatically**. Your pairing, history and files are never touched.

**Android app.** A banner appears on the home screen: tap **UPDATE**. The first time, Android asks you to allow Tonefer to install apps; after that it is one tap plus Android's own confirmation. No uninstalling.

**Running from source.** `git pull`, then restart. The Update button does this for you.

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
