# PrintView

Watch and control a **Bambu Lab P1S** from your phone or any browser, with AI spaghetti detection, timelapses, a print queue and a public web link. It all runs on a **Raspberry Pi 5** at your home. No Bambu cloud needed.

**Live demo (my printer, view-only):** https://printwatch.tail9ea1be.ts.net:10000/yDTJstKkrryn8tdm

---

## Install it (step by step, no experience needed)

Total time: about 45 minutes, mostly waiting.

### What you need

| Thing | Notes |
|---|---|
| Raspberry Pi 5 | 4 GB or 8 GB is best. 2 GB works, but slower: the 3D preview, timelapse videos and training take longer, and it can lag with lots of viewers |
| Official Raspberry Pi 27 W power supply | Weaker chargers make the Pi crash |
| microSD card, 32 GB or bigger | Or a USB SSD |
| A computer | Windows, Mac or Linux, just for setting up the card |
| Bambu Lab P1S | Firmware 01.08.02.00 or newer, on the same Wi-Fi/network as the Pi |
| Android phone | Optional, for the app |

### Step 1: Get the printer ready

On the printer's screen:

1. Go to **Settings > WLAN / Network**.
2. Turn **LAN Only Mode** on.
3. Turn the printer **off and on** once.
4. Go back to **Settings > WLAN / Network** and turn **Developer Mode** on.
5. On that same page, write down:
   - the **IP address** (looks like `192.168.1.50`)
   - the **Access Code** (8 characters)
6. Write down the **serial number**. It's on the sticker on the back of the printer, and in Bambu Studio under **Device**.

> LAN Only Mode means the Bambu Handy app and Bambu cloud stop working with this printer. Bambu Studio still works over your Wi-Fi.

### Step 2: Put Raspberry Pi OS on the card

1. On your computer, download and install **Raspberry Pi Imager** from https://www.raspberrypi.com/software/
2. Put the microSD card in your computer and open Raspberry Pi Imager.
3. Choose:
   - **Device:** Raspberry Pi 5
   - **Operating system:** Raspberry Pi OS **(64-bit)**
   - **Storage:** your microSD card
4. When it asks about customization, choose **Edit settings** / customize and fill in:
   - a **username** and **password** (write them down)
   - your **Wi-Fi name and password** (skip if you'll use a network cable)
   - turn on **SSH** (under Services)
5. Write the card, put it in the Pi, plug in power, and wait about 2 minutes.

### Step 3: Open a terminal on the Pi

Either one works:
- **Screen and keyboard on the Pi:** click the black terminal icon at the top.
- **From your computer:** open Terminal (Mac/Linux) or PowerShell (Windows) and type `ssh yourusername@raspberrypi.local`, then your password.

Everything below is typed into that terminal. Paste a line, press **Enter**, and wait until it finishes.

### Step 4: Download PrintView and run the installer

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/wvfouram/printview.git ~/printview
cd ~/printview && chmod +x install.sh && ./install.sh
```

The **first time**, the installer sets up Docker and then tells you to restart. Do that:

```bash
sudo reboot
```

Wait 1 minute, open the terminal again (Step 3), and run the installer a second time:

```bash
cd ~/printview && ./install.sh
```

Now it asks for the **IP, serial number and access code** from Step 1, checks it can reach the printer, and builds PrintView. That takes 5 to 15 minutes the first time. When it's done it prints an address like:

```
PrintView is running: http://192.168.1.60:8080
```

Open that address on a phone or computer on the same Wi-Fi. You should see the printer camera.

### Step 5 (optional): The public web link

At the end, the installer asks **"Set it up now? (y/N)"**. Type `y` to get a link that works from anywhere:

1. Choose a **general code** (controls the printer) and a **master code** (also opens the Owner page). Use different codes.
2. The installer installs **Tailscale** (free) and shows a login link. Open it on any device and sign in with Google, Microsoft or GitHub.
3. If Tailscale asks you to **enable HTTPS** and **Funnel**, click to approve, then run `./install.sh` once more.
4. It prints your public link, like `https://raspberrypi.tail1234.ts.net:10000/AbCdEf123`.

Anyone with that link can **watch**. Controlling the printer needs your general or master code.

### Step 6 (optional): The Android app

1. On your phone, open the **[Releases](../../releases)** page and download **PrintView.apk**.
2. Open it and allow installing from your browser if Android asks.
3. In the app, tap the **gear icon**, type the address from Step 4 (like `http://192.168.1.60:8080`), and tap **Save**.
4. Do this the first time while the phone is on your home Wi-Fi. The app pairs with the Pi by itself and then also works away from home.

### iPhone

There's no iPhone app, but the website does almost everything the Android app does (everything except the floating camera and live sound).

1. Set up the public web link (Step 5).
2. Open your public link in **Safari**.
3. Tap the **Share** button, then **Add to Home Screen**, then **Add**.
4. Open it from the new icon on your home screen. It opens full screen like an app, at home or away.

Phone alerts work on iPhone too: the ntfy app is on the App Store (Step 7).

### Step 7 (optional): Phone alerts

1. Install the **ntfy** app on your phone.
2. In ntfy, subscribe to a long, random topic name, for example `printview-7f3k9q2xv8`.
3. On the Pi:
   ```bash
   cd ~/printview && nano .env
   ```
   Set `NTFY_URL=https://ntfy.sh/printview-7f3k9q2xv8`, press **Ctrl+O**, **Enter**, **Ctrl+X**, then run `./install.sh`.

You'll get alerts for failures, auto-pauses, finished prints and a weekly report.

---

## Updating

```bash
cd ~/printview && git pull && ./install.sh
```

## If something doesn't work

| What you see | What to do |
|---|---|
| Installer says "This needs the 64-bit Raspberry Pi OS" | Re-do Step 2 and pick **Raspberry Pi OS (64-bit)** |
| Installer says ports don't answer | Check LAN Only Mode and Developer Mode are on, and the IP is right (it can change after a router restart) |
| "PRINTER OFFLINE" on the page | Same as above. The access code changes if you turn LAN Only Mode off and on: run `nano .env`, fix `ACCESS_CODE`, then `./install.sh` |
| Camera offline | Close the live view in Bambu Studio; the printer allows only one camera viewer at a time |
| Too many false spaghetti alarms | Safety tab > Sensitivity > Low |
| Something else | `cd ~/printview && docker compose logs --tail 50` and open an issue with the output |

---

## What it can do

- **Live camera** under every page, with live status: percent, time left, finish time, layer, temperatures, Pause / Stop.
- **Print tab:** SD card files with slicer thumbnails, an interactive **3D toolpath preview**, filament-to-AMS mapping, start now, **schedule for later**, or add to the **print queue** and tap *Start next* when a print is done. Upload, download, delete (deleted files are kept on the Pi). Skip objects mid-print.
- **Control tab:** speed modes, temperatures with presets, fans, moving the axes, printer options, calibration, and a G-code console (master code).
- **AMS tab:** every AMS unit and slot (including AMS HT), temperature and humidity, load / unload, set filament, K values.
- **Safety tab:** local AI **spaghetti detection** with auto-pause, a **clear-plate check** when a print starts, and your own trainable model.
- **Videos tab:** smooth per-layer **timelapses** made by the Pi, timelapses from the SD card, and print history with a photo of every finished print.
- **Printer tab:** everything the printer reports, activity log, firmware versions (serial numbers hidden).
- **Android app** with the same features, a floating camera on every screen, and direct, paired access from anywhere.
- **Public web link** with view-only visitors, a general code, and a master code with an Owner page (freeze everyone, change the general code, see who's watching).

## Everyday commands

Run these in `~/printview`:

```bash
docker compose logs -f        # watch what it's doing (Ctrl+C to stop watching)
docker compose restart        # restart it
./install.sh                  # apply changes after editing .env
docker compose down           # stop it
```

## Advanced

<details><summary>Settings in .env</summary>

| Setting | Meaning |
|---|---|
| `PRINTER_IP`, `PRINTER_SERIAL`, `ACCESS_CODE` | From the printer (Step 1) |
| `APP_PIN` | Optional PIN to lock the web app on your Wi-Fi |
| `NTFY_URL` | Phone alerts (Step 7) |
| `REMOTE=on`, `REMOTE_PORT=8443`, `UPNP=on`, `REMOTE_HOST=` | How the Android app reaches the Pi away from home. With UPnP on, your router forwards port 8443 by itself. If UPnP is off, forward TCP 8443 to the Pi in your router and set `REMOTE_HOST` to your public IP |
| `DATASET_MAX_GB=3` | How much space detection recordings may use |

</details>

<details><summary>How the spaghetti detection works</summary>

PrintView runs [Obico](https://github.com/TheSpaghettiDetective/obico-server)'s open-source failure-detection model on the Pi, with no cloud. It checks a frame every 10 seconds while printing. The first minutes of each print are a warm-up. A warning sends a phone alert; a failure pauses the print (if auto-pause is on) and sends the picture.

Every print is recorded (a frame every 10 s). Finished prints are marked good automatically; failed or flagged ones wait for you to mark where the failure started in the Safety tab. With 3 failed and 3 good prints, your own model can take over the pause decision. The Safety tab shows how it scores on your past prints, compared with Obico's stock model.

</details>

<details><summary>Arduino bed relay (optional)</summary>

The `arduino/` folder has sketches for an Arduino Uno that switches an external bed heater through a relay, controlled by PrintView. Not needed for anything else.

</details>

## Notes

- The P1S camera sends about 1 picture per second over the network. That's the printer's limit.
- Your settings, recordings, timelapses and trained model are stored in `~/printview/data`. Back it up to keep them.
- The spaghetti model comes from Obico (AGPL-3.0) and is downloaded during the build.
