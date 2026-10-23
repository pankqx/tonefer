# tonefer — the simple guide

No GitHub knowledge needed. Read top to bottom once.

> **Nothing gets installed on your phone.** tonefer runs on the **laptop**. The phone just opens a page in Chrome by scanning a QR code.

---

## Part 1 — Put tonefer on your laptop (one time)

Open a terminal (**Ctrl + Alt + T** on Ubuntu) and paste these lines one at a time. Press Enter after each.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
cd ~
git clone https://github.com/pankqx/tonefer.git
```

You now have a folder called `tonefer` in your home folder.

**No git? Use the ZIP instead.** Open github.com/pankqx/tonefer, click the green **Code** button, then **Download ZIP**. Extract it into your home folder and rename the folder to `tonefer`.

---

## Part 2 — Start it (every time you want to use it)

```bash
cd ~/tonefer
./run.sh
```

- The **first run** takes about a minute while it installs what it needs.
- If it asks **"Allow port 8765 through it now?"**, type `y`, press Enter and type your laptop password. That firewall step is the usual cause of *"This site can't be reached"*.
- A browser window opens with tonefer. Keep the terminal open; closing it stops tonefer.

---

## Part 3 — Connect your phone (one time)

1. On the phone: **Settings → Hotspot → turn it on.**
2. On the laptop: click the Wi‑Fi icon (top-right) and **join your phone's hotspot**.
3. Look at the tonefer window. The left card should show the laptop is on your hotspot, with a QR code under the title **Pair your phone**.
4. Point the **phone camera** at the QR code and tap the link.
5. In Chrome on the phone, tap **⋮ → Add to Home screen**. tonefer now opens like an app.

From now on you only need Part 2, then tap the tonefer icon on your phone.

---

## Using it

| You want to… | Do this |
|---|---|
| Send a note to the phone | Type in the laptop box, press **Enter** |
| Send a photo to the phone | Drag it onto the laptop window, or **Ctrl + V** a copied image |
| Send a photo to the laptop | On the phone tap **+**, then choose photos |
| Copy a note | Tap the copy icon on the message |
| Save a photo on the phone | Tap it, then **Save** (it goes to Downloads) |
| Find received files on the laptop | Click **Open Tonefer folder** (`~/Tonefer/Received`) |

---

## Getting the newest version later

```bash
cd ~/tonefer
git pull
./run.sh
```

If you used the ZIP, download it again and replace the folder. Your history and pairing are kept, because they live in `~/.tonefer`, not in the folder.

After updating, close the tonefer tab on the phone and open it again so it loads the new look.

---

## "This site can't be reached" on the phone

Check these in order:

1. **Is the laptop on the phone's hotspot?** The left card in tonefer shows which Wi‑Fi it's on.
2. **Is tonefer running?** The terminal from Part 2 must still be open.
3. **Is the firewall open?** Run `sudo ufw allow 8765/tcp`
4. **Are you scanning the current code?** The code changes when the laptop changes network.
5. **Can you type the address?** The tonefer card shows it under the QR code, like `10.42.0.15:8765`. Type it into Chrome on the phone.
6. **Still stuck?** Run `cd ~/tonefer && ./run.sh doctor` and send the output to whoever is helping you.

---

## Windows (after you switch)

1. Install Python from **python.org**. Tick **"Add Python to PATH"** during setup.
2. Download the ZIP (Part 1) and extract it.
3. Double-click **`run.bat`**.
4. When Windows Firewall asks, allow **Private networks**.
5. Set the hotspot connection to Private: **Settings → Network & internet → Wi‑Fi → your hotspot → Private network.**

---

## Starting over

- **Unpair all phones** (laptop sidebar): every phone has to scan again.
- **Clear history**: empties the timeline on both devices. Files stay in `~/Tonefer`.
