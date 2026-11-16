#!/usr/bin/env bash
# Installs PrintView Admin on the Pi: a background service (only reachable from the Pi itself)
# plus a "PrintView Admin" icon on the desktop and in the menu.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/pvadmin"
cp "$SRC/pvadmin.py" "$HOME/pvadmin/pvadmin.py"

sudo tee /etc/systemd/system/pvadmin.service >/dev/null <<UNIT
[Unit]
Description=PrintView Admin (local only)
After=network-online.target docker.service

[Service]
User=$USER
WorkingDirectory=$HOME/pvadmin
ExecStart=/usr/bin/python3 $HOME/pvadmin/pvadmin.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now pvadmin
sudo systemctl restart pvadmin

BROWSER=$(command -v chromium || command -v chromium-browser || echo chromium)
mkdir -p "$HOME/.local/share/applications" "$HOME/Desktop"
for f in "$HOME/.local/share/applications/pvadmin.desktop" "$HOME/Desktop/pvadmin.desktop"; do
  cat > "$f" <<DESK
[Desktop Entry]
Type=Application
Name=PrintView Admin
Comment=Full control of PrintView (this Pi only)
Exec=$BROWSER --app=http://127.0.0.1:8095 --window-size=1400,900 --class=PrintViewAdmin
Icon=applications-system
Terminal=false
Categories=Utility;
DESK
  chmod +x "$f"
done
gio set "$HOME/Desktop/pvadmin.desktop" metadata::trusted true 2>/dev/null || true
sleep 2
if curl -fs http://127.0.0.1:8095/me >/dev/null; then
  echo "PrintView Admin is running. Open it from the desktop icon or the menu (Accessories / Other)."
else
  echo "The admin service didn't start. Check:  sudo journalctl -u pvadmin -n 30"
fi
