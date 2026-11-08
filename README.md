# PrintView

Live camera, pause / resume / stop, chamber light, and local spaghetti detection for a Bambu Lab P1S in LAN-only + Developer Mode. Runs on a Raspberry Pi 5. You control it from a phone web app that you add to your home screen.

## Install on the Pi

```bash
# copy printwatch.zip to the Pi first (see below), then:
unzip printwatch.zip && cd printwatch
chmod +x install.sh
./install.sh
```

The installer asks for the printer IP, serial number, access code, an optional app PIN, and an optional ntfy URL. It checks that the printer is reachable, builds the container, and prints the address to open on your phone. The first build takes about 5 to 10 minutes on a Pi 5.

**Copy the zip from your computer to the Pi:**
```bash
scp printwatch.zip <pi-user>@<pi-ip>:~
```

## Phone app

Open `http://<pi-ip>:8080` on your phone while it's on the same Wi-Fi, then add it to your home screen:
- **iPhone:** Safari > Share > Add to Home Screen. It opens full screen like an app.
- **Android:** Chrome > menu > Add to Home screen.

The app gives you:
- **Live view** of the printer camera, with a full-screen button and a chamber light toggle.
- **Status:** progress, time remaining and ETA, layer, and nozzle and bed temperatures.
- **Pause / Resume** with one tap. **Stop** needs a press-and-hold to confirm.
- **Spaghetti watch:** a live failure score, an auto-pause toggle, sensitivity (Low / Med / High), and the last flagged frame with boxes drawn on it.
- **Activity log** of starts, pauses, detections and finishes.

## Printer controls (Android app → Printer controls)

Everything the P1S accepts over LAN MQTT:
- **Print speed:** Silent / Standard / Sport / Ludicrous, mid-print.
- **Temperatures:** nozzle and bed targets (±5°, exact value, PLA/PETG/ABS/TPU presets, cool down). Capped at the P1S maximums of 300° nozzle and 100° bed.
- **Fans:** part cooling, aux and chamber, 0-100%.
- **AMS:** see every slot's material, color and remaining amount; tap a slot to load it, set its filament type/color/temps (for non-RFID spools), or re-read its RFID tag; unload; retry after an AMS error. Shows AMS temperature, humidity and drying time left (AMS 2 Pro / AMS HT). Drying itself can only be started from the P1S screen; the P1 series doesn't accept drying commands over the network.
- **Move:** home, jog X/Y/Z in 1/10/50 mm steps, motors off. **Locked while a print is running or paused.**
- **G-code console:** sends raw G-code. Movement commands are refused while printing.
- **Printer options:** auto-recover from step loss, AMS auto-refill, RFID reading at power-on / insert, remaining-filament estimate.
- **Calibration:** bed leveling, vibration compensation, motor noise cancellation.
- **Extrude / retract** 10 mm (nozzle must be 170°+).
- **Printer info:** current stage, Wi-Fi signal, nozzle size and any HMS error codes (tap to open Bambu's wiki page for the code).

## SD card (app: Print from SD card, Current job, Timelapses)

Read straight from the printer's SD card over its LAN FTPS port:
- **Print from SD card:** every sliced `.3mf` (from Bambu Studio / OrcaSlicer "Send"), with plate preview, print time and weight. Pick the plate, map each filament to an AMS slot (auto-matched by type and color), choose timelapse / bed leveling / flow / vibration calibration, start.
- **Current job:** plate preview and **skip objects**.
- **Timelapses:** list with thumbnails; download into the app (works away from home too), then play or save/share.

## Spaghetti detection

PrintWatch runs Obico's open-source failure-detection model locally on the Pi CPU, with no cloud involved. It checks a frame every 10 seconds while the printer is printing, using Obico's own scoring algorithm and tuned thresholds:
- The first **5 minutes** of each print are a warm-up and won't trigger.
- **Warning:** you get a push alert (if ntfy is set up) and an entry in the log.
- **Failure:** the print auto-pauses (if enabled) and you get an urgent alert with the flagged image.
- After you resume, there's a 1-minute grace period before checking starts again.

Keep the chamber light on during prints so the camera has enough light to see.

## Training your own model

Every print gets recorded automatically: one frame every 10 seconds, plus the features the Obico network extracts from it. Open **Train** from the Spaghetti watch card to see them.

- **Prints that finish cleanly** get marked good on their own.
- **Failed, stopped or flagged prints** go into "Needs review." Open one, drag to the first frame where it went wrong, and tap **Failure started here**. If nothing actually went wrong, tap **Whole print was fine**.
- The app retrains on the Pi automatically about 20 seconds after you label something, which takes a few seconds. You can also tap **Train now**.
- Once you have 3 failed and 3 good prints, your model takes over the pause decision, and Obico drops to sending warnings only. You can switch back with **Use my model**.

**Accuracy you can trust:** the Train screen shows how your model does on **your** past prints. It uses cross-validation, so each print is scored by a model that never saw it. Next to that, it shows how Obico's stock algorithm did on the same prints. The pause threshold is chosen automatically, counting a false alarm as 1.5 times worse than a missed failure. The sensitivity setting shifts it up or down.

**Getting failures on purpose:** knock over a tall, thin tower mid-print, or print PETG without glue so it lets go of the bed. Do this in several filament colors, including black and white, which are the hardest for the camera to see. 10 or more failures makes a strong model.

Recordings take up about 10 MB per hour of printing. When the dataset goes over `DATASET_MAX_GB` (3 by default), the app deletes thumbnails from the oldest good prints first. It keeps their features, so those prints still count for training.

## Away from home: phone ↔ Pi, nothing in between

The Android app talks straight to the Pi: plain HTTP on your home Wi-Fi, and **HTTPS on port 8443** everywhere else. No VPN app, relay or cloud.

- **Pairing is automatic:** the first time the app reaches the Pi on your home Wi-Fi, it gets a private device key and the Pi's certificate fingerprint. Away from home the app only trusts *that* certificate and sends that key, so nobody else can connect, even if they find the port.
- **Router forwarding is automatic when UPnP is on** (most home routers, including Xfinity, have it on by default). The Pi also learns your public address from the router. Check the result in the app under the gear icon.
- **If UPnP is off:** in your router, forward **TCP 8443** to the Pi (10.0.0.43), and set `REMOTE_HOST=<your public IP>` in `.env`.
- 10 wrong keys from one address block it for an hour. Re-pair a phone with the gear icon, then Re-pair, on home Wi-Fi.
- `.env` options: `REMOTE=off` disables it, `REMOTE_PORT=8443`, `UPNP=off`, `REMOTE_HOST=`.

If your internet provider uses CGNAT (shared public address), nothing at home can be reached from outside; the app will warn you.

## Push alerts (optional)

1. Install the **ntfy** app (iOS or Android).
2. Subscribe to a long, random topic name, for example `printwatch-7f3k9q2xv8`.
3. Set `NTFY_URL=https://ntfy.sh/printwatch-7f3k9q2xv8` in `.env`, then run `docker compose up -d`.

You'll get alerts for possible failures, auto-pauses, and finished or failed prints. Anyone who knows the topic name can read these alerts, so make it hard to guess.

## Everyday commands (run in the printwatch folder)

```bash
docker compose logs -f        # watch logs
docker compose restart        # restart
docker compose up -d --build  # apply changes to .env or code
docker compose down           # stop
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Printer dot red | Confirm LAN Only Mode and Developer Mode are on, and check the IP and access code in `.env`. The access code changes if you toggle LAN mode. |
| Camera offline | Port 6000 must be reachable. Close Bambu Studio's live view, because the printer may only allow one camera viewer at a time. |
| "Bad frame size" | Wrong access code. |
| Detection says model not found | The model download failed during the build. Run `docker compose build --no-cache`. |
| Too many false alarms | Set sensitivity to Low. |

## Notes

- The P1S camera runs at about 0.5 fps over LAN, which is a limit of the printer.
- `http://<pi-ip>:8080/stream.mjpg` is a standard MJPEG stream you can use in VLC or Home Assistant. It's also the starting point for streaming to the web later.
- Settings, the event log, recordings and your trained model are stored in `./data`. Back it up to keep your model.
- The spaghetti model comes from [Obico](https://github.com/TheSpaghettiDetective/obico-server) (AGPL-3.0) and is downloaded during the build.
