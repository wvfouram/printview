#!/usr/bin/env bash
# Installs PrintView Admin, a real desktop app on the Pi (GTK), with an icon on the desktop and in the menu.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "== Making sure the app toolkit is installed"
python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null \
  || sudo apt-get install -y python3-gi gir1.2-gtk-3.0

echo "== Copying the app"
mkdir -p "$HOME/pvadmin"
cp "$SRC/printview_admin.py" "$SRC/pvadmin.py" "$HOME/pvadmin/"
chmod +x "$HOME/pvadmin/printview_admin.py"
cat > "$HOME/pvadmin/icon.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#141619"/><rect x="12" y="14" width="40" height="30" rx="5" fill="none" stroke="#ffb224" stroke-width="4"/><circle cx="32" cy="29" r="7" fill="#ffb224"/><rect x="20" y="48" width="24" height="5" rx="2.5" fill="#34d399"/></svg>
SVG

# The old browser-based version is no longer needed
if systemctl list-unit-files 2>/dev/null | grep -q '^pvadmin.service'; then
  echo "== Removing the old browser version"
  sudo systemctl disable --now pvadmin 2>/dev/null || true
  sudo rm -f /etc/systemd/system/pvadmin.service
  sudo systemctl daemon-reload
fi

echo "== Adding the desktop icon and menu entry"
mkdir -p "$HOME/.local/share/applications" "$HOME/Desktop"
for f in "$HOME/.local/share/applications/pvadmin.desktop" "$HOME/Desktop/pvadmin.desktop"; do
  cat > "$f" <<DESK
[Desktop Entry]
Type=Application
Name=PrintView Admin
Comment=Full control of PrintView (this Pi only)
Exec=/usr/bin/python3 $HOME/pvadmin/printview_admin.py
Icon=$HOME/pvadmin/icon.svg
Terminal=false
Categories=Utility;
StartupWMClass=printview_admin.py
DESK
  chmod +x "$f"
done
gio set "$HOME/Desktop/pvadmin.desktop" metadata::trusted true 2>/dev/null || true

echo "== ALL DONE. Open PrintView Admin from the desktop icon or the menu (Accessories)."
