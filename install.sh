#!/usr/bin/env bash
# PrintWatch installer for Raspberry Pi 5 (Raspberry Pi OS 64-bit + Docker)
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1;33m==>\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*"; exit 1; }

command -v docker >/dev/null || fail "Docker not found. Run: curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker \$USER  (then log out/in)"
docker compose version >/dev/null 2>&1 || fail "'docker compose' plugin missing. Re-run the get.docker.com script."
docker info >/dev/null 2>&1 || fail "Can't talk to Docker. Log out and back in after 'usermod -aG docker', or run with sudo."

if [[ ! -f .env ]]; then
  say "Printer details (on the P1S: Settings > Network / Device)"
  read -rp "Printer IP: " IP
  read -rp "Printer serial number: " SERIAL
  read -rsp "Access code (hidden): " CODE; echo
  read -rsp "App PIN to lock the phone app (blank = no PIN): " PIN; echo
  read -rp "ntfy URL for push alerts (blank = off): " NTFY
  umask 077
  cat > .env <<EOF
PRINTER_IP=${IP}
PRINTER_SERIAL=${SERIAL}
ACCESS_CODE=${CODE}
APP_PIN=${PIN}
PORT=8080
NTFY_URL=${NTFY}
EOF
  say "Saved settings to .env (edit it anytime, then re-run ./install.sh)"
fi

set -a; source .env; set +a

say "Checking the printer at ${PRINTER_IP}..."
for port in 8883 6000; do
  if timeout 4 bash -c "</dev/tcp/${PRINTER_IP}/${port}" 2>/dev/null; then
    echo "  port ${port}: OK"
  else
    echo "  port ${port}: NOT reachable - is the printer on, in LAN Only mode, and is the IP right?"
  fi
done

mkdir -p data
say "Building and starting PrintWatch (first build takes a few minutes)..."
docker compose up -d --build

PI_IP=$(hostname -I | awk '{print $1}')
say "Done. Open on your phone:  http://${PI_IP}:${PORT:-8080}"
echo "    iPhone: Safari > Share > Add to Home Screen"
echo "    Android: Chrome > menu > Add to Home screen"
echo
echo "    Logs:    docker compose logs -f"
echo "    Restart: docker compose restart"
