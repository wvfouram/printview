#!/usr/bin/env bash
# PrintView installer for a Raspberry Pi 5 (Raspberry Pi OS 64-bit).
# Run it from the printview folder:   ./install.sh
# Safe to run again: it keeps your settings and only fills in what's missing.
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1;33m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[1;32mOK\033[0m %s\n' "$*"; }
warn() { printf '    \033[1;31m!!\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31mSTOPPED:\033[0m %s\n' "$*"; exit 1; }

# ---------------------------------------------------------------- 1. checks
[[ "$(uname -m)" == "aarch64" ]] || fail "This needs the 64-bit Raspberry Pi OS (yours reports $(uname -m)). Re-flash the card with 'Raspberry Pi OS (64-bit)'."

if ! command -v docker >/dev/null; then
  say "Docker isn't installed yet. Installing it now (takes a few minutes)..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  say "Docker installed. Reboot once so it takes effect:"
  echo "      sudo reboot"
  echo "    After the Pi is back, open a terminal and run the same thing again:"
  echo "      cd ~/printview && ./install.sh"
  exit 0
fi
docker compose version >/dev/null 2>&1 || fail "The 'docker compose' part is missing. Run: curl -fsSL https://get.docker.com | sudo sh   then run ./install.sh again."
docker info >/dev/null 2>&1 || fail "Docker is installed but you can't use it yet. Reboot (sudo reboot), then run ./install.sh again."
ok "Docker is ready"

# ---------------------------------------------------------------- 2. printer details
if [[ ! -f .env ]]; then
  say "Printer details. On the P1S screen: Settings > WLAN / Network"
  echo "    (LAN Only Mode and Developer Mode must be ON. The access code and IP are on that same page."
  echo "     The serial number is on the sticker on the back of the printer, or in Bambu Studio > Device.)"
  read -rp  "    Printer IP address (like 192.168.1.50): " IP
  read -rp  "    Printer serial number (15 letters/numbers): " SERIAL
  read -rp  "    Access code (8 characters): " CODE
  read -rp  "    PIN to lock the phone web app (press Enter for none): " PIN
  read -rp  "    ntfy address for phone alerts (press Enter to skip, see README): " NTFY
  umask 077
  cat > .env <<EOF
PRINTER_IP=${IP}
PRINTER_SERIAL=${SERIAL}
ACCESS_CODE=${CODE}
APP_PIN=${PIN}
PORT=8080
NTFY_URL=${NTFY}
EOF
  ok "Saved to .env (to change something later: nano .env, then ./install.sh)"
fi
set -a; source .env; set +a

say "Checking the printer at ${PRINTER_IP}..."
bad=0
for port in 8883 6000 990; do
  if timeout 4 bash -c "</dev/tcp/${PRINTER_IP}/${port}" 2>/dev/null; then ok "port ${port} answers"; else warn "port ${port} doesn't answer"; bad=1; fi
done
[[ $bad == 0 ]] || warn "Check: printer on, LAN Only Mode on, Developer Mode on, and the IP is right. Continuing anyway."

# ---------------------------------------------------------------- 3. build + start
mkdir -p data
say "Building and starting PrintView. The first time takes 5 to 15 minutes, later runs are quick..."
docker compose up -d --build
PI_IP=$(hostname -I | awk '{print $1}')
ok "PrintView is running: http://${PI_IP}:${PORT:-8080}  (open it on a phone or computer on the same Wi-Fi)"

# ---------------------------------------------------------------- 4. optional public web link
say "Optional: a public web link (watch and control from anywhere, protected by your own codes)"
read -rp "    Set it up now? (y/N): " WANT
if [[ "${WANT,,}" == y* ]]; then
  if [[ ! -f camview/.env ]]; then
    echo "    Pick two codes. The general code controls the printer; the master code also opens the Owner page."
    read -rp "    General code: " GC
    read -rp "    Master code (different from the general code): " MC
    [[ -n "$GC" && -n "$MC" && "$GC" != "$MC" ]] || fail "Both codes are needed and they must be different. Run ./install.sh again."
    ( umask 077; printf 'ACCESS_CODE=%s\nMASTER_CODE=%s\n' "$GC" "$MC" > camview/.env )
    ok "Codes saved to camview/.env"
  fi
  mkdir -p camview/data
  ( cd camview && docker compose up -d )
  sleep 3
  LINKPATH=$(docker logs camview 2>&1 | grep -o 'link path: .*' | tail -1 | sed 's/link path: //')
  if ! command -v tailscale >/dev/null; then
    say "Installing Tailscale (it carries the public link, free for personal use)..."
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
  if ! tailscale status >/dev/null 2>&1; then
    say "Sign in to Tailscale: open the link that appears below on any device and log in."
    sudo tailscale up
  fi
  say "Turning on the public link (if a page asks you to enable HTTPS / Funnel, approve it, then run ./install.sh again)..."
  sudo tailscale funnel --bg --https=10000 http://127.0.0.1:8090 || fail "Funnel wasn't allowed yet. Approve it in the page Tailscale showed, then run ./install.sh again."
  HOST=$(tailscale status --json | python3 -c 'import sys,json; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
  ok "Public link:  https://${HOST}:10000${LINKPATH}"
  echo "    Anyone with this link can watch. Controls need your general or master code."
fi

say "All done."
PI_IP=$(hostname -I | awk '{print $1}')
echo "    Android app: install PrintView.apk from the Releases page on GitHub, open it, tap the gear icon,"
echo "    type  http://${PI_IP}:8080  and tap Save (do this on your home Wi-Fi so the phone pairs)."
echo "    Logs:     cd ~/printview && docker compose logs -f"
echo "    Restart:  cd ~/printview && docker compose restart"
