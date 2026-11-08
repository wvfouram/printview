"""PrintWatch for Windows: the same thing the Raspberry Pi runs, in one window.

Runs the printer app (camera, controls, failure detection) on http://<this PC>:8080 and the
public web link server, and sets up the Tailscale link if Tailscale is installed.
Settings and data live in %LOCALAPPDATA%\\PrintWatch. Close the window to stop it.
"""
import ctypes
import getpass
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
DATA = os.path.join(os.environ.get("LOCALAPPDATA") or HERE, "PrintWatch")
CONF = os.path.join(DATA, "config.json")
MODEL = os.path.join(DATA, "models", "failure.onnx")
MODEL_URL = "https://www.obico.io/static_pub/ml-models/model-weights-5a6b1be1fa.onnx"
MODEL_SHA = "0a6ebd8e30dbf6a450c50f9c0a5406f04ba7eb1c99fd5996e888c78bb383b9aa"
TAILSCALE = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe")
STARTUP = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", "PrintWatch.cmd")


def title(t):
    try:
        ctypes.windll.kernel32.SetConsoleTitleW(t)
    except Exception:
        pass


def ask(q, default="", secret=False, check=None):
    while True:
        p = f"{q}{f' [{default}]' if default else ''}: "
        v = (getpass.getpass(p) if secret else input(p)).strip() or default
        err = check(v) if check else (None if v else "required")
        if not err:
            return v
        print("  " + err)


def port_open(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=4):
            return True
    except OSError:
        return False


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "localhost"


def setup(old=None):
    old = old or {}
    print("\n=== PrintWatch setup ===")
    print("On the printer: Settings > WLAN shows the IP, Settings > LAN Only Mode shows the access code,")
    print("Settings > Device shows the serial number. Turn on LAN Only Mode and Developer Mode.\n")
    c = {}
    c["ip"] = ask("Printer IP address", old.get("ip", ""))
    c["serial"] = ask("Printer serial number", old.get("serial", "")).upper().replace(" ", "")
    c["code"] = ask("Printer access code (8 characters, hidden)" + (" - Enter keeps the old one" if old.get("code") else ""),
                    old.get("code", ""), secret=True)
    for port, what in ((8883, "controls"), (6000, "camera")):
        print(f"  {what} (port {port}): {'OK' if port_open(c['ip'], port) else 'NOT reachable - check the IP and LAN Only Mode'}")
    print("\nWeb link passwords (people with the link need these to control the printer).")
    num = lambda v: None if v.isdigit() and 4 <= len(v) <= 12 else "use 4-12 digits"
    c["web_code"] = ask("General access code", old.get("web_code", ""), check=num)
    c["master_code"] = ask("Master code (command center)", old.get("master_code", ""),
                           check=lambda v: num(v) or ("must be different from the general code" if v == c["web_code"] else None))
    c["pin"] = input("PIN to lock the app on your home Wi-Fi (Enter = no PIN): ").strip()
    auto = ask("Start PrintWatch when Windows starts? (y/n)", "y" if old.get("autostart", True) else "n",
               check=lambda v: None if v.lower() in ("y", "n") else "y or n")
    c["autostart"] = auto.lower() == "y"
    os.makedirs(DATA, exist_ok=True)
    with open(CONF, "w") as f:
        json.dump(c, f, indent=1)
    exe = os.path.join(os.path.dirname(HERE), "PrintWatch.exe")
    try:
        if c["autostart"]:
            with open(STARTUP, "w") as f:
                f.write(f'@start "" /min "{exe}"\r\n')
        elif os.path.exists(STARTUP):
            os.remove(STARTUP)
    except OSError as e:
        print("  couldn't change start-with-Windows:", e)
    print("Saved. To change these later, run PrintWatch.exe --setup\n")
    return c


def get_model():
    if os.path.exists(MODEL):
        return
    print("Downloading the failure-detection model (one time)...")
    os.makedirs(os.path.dirname(MODEL), exist_ok=True)
    try:
        import certifi
        import ssl
        ctx = ssl.create_default_context(cafile=certifi.where())
        h = hashlib.sha256()
        tmp = MODEL + ".part"
        with urllib.request.urlopen(MODEL_URL, timeout=60, context=ctx) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                h.update(chunk)
                f.write(chunk)
        if h.hexdigest() != MODEL_SHA:
            os.remove(tmp)
            raise ValueError("download was corrupted")
        os.replace(tmp, MODEL)
        print("  model ready")
    except Exception as e:  # noqa: BLE001
        print(f"  couldn't download it ({e}). Everything else works; failure detection stays off until next start.")


def tailscale_link(path):
    """If Tailscale is installed and logged in, publish the web link on port 10000 and return the full URL."""
    if not os.path.exists(TAILSCALE):
        return None, "Tailscale isn't installed (see README.txt to get a public link)."
    try:
        st = json.loads(subprocess.run([TAILSCALE, "status", "--json"], capture_output=True, timeout=15,
                                       creationflags=0x08000000).stdout or b"{}")
        name = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if not name or st.get("BackendState") != "Running":
            return None, "Tailscale is installed but not logged in. Open Tailscale and log in, then restart PrintWatch."
        r = subprocess.run([TAILSCALE, "funnel", "--bg", "--https=10000", "http://127.0.0.1:8090"],
                           capture_output=True, text=True, timeout=30, creationflags=0x08000000)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip().splitlines()
            return None, "Tailscale said: " + (msg[-1] if msg else "error") + "  (see README.txt, Funnel may need turning on once)"
        return f"https://{name}:10000{path}", None
    except Exception as e:  # noqa: BLE001
        return None, f"Tailscale check failed: {e}"


def run_camview(c, link_path):
    env = dict(os.environ, PORT="8090", OWNER_PORT="8091", APP="http://127.0.0.1:8080",
               ACCESS_CODE=c["web_code"], MASTER_CODE=c["master_code"], CAMVIEW_DATA=os.path.join(DATA, "camview"),
               PYTHONUNBUFFERED="1")
    while True:
        p = subprocess.Popen([PY, os.path.join(HERE, "camview", "camview.py")], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=0x08000000)
        for line in p.stdout:
            line = line.rstrip()
            if line.startswith("link path: "):
                link_path[0] = line[len("link path: "):]
            elif line:
                print("[web link] " + line, flush=True)
        p.wait()
        print("[web link] stopped, restarting in 5 s", flush=True)
        time.sleep(5)


def main():
    title("PrintWatch - keep this window open")
    print("PrintWatch for Windows")
    conf = None
    if os.path.exists(CONF):
        try:
            conf = json.load(open(CONF))
        except ValueError:
            conf = None
    if conf is None or "--setup" in sys.argv:
        conf = setup(conf)
    get_model()

    # keep the PC from sleeping while this runs (the screen can still turn off)
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    except Exception:
        pass

    link_path = [None]
    threading.Thread(target=run_camview, args=(conf, link_path), daemon=True).start()

    def announce():
        for _ in range(60):
            if link_path[0]:
                break
            time.sleep(0.5)
        url, why = tailscale_link(link_path[0] or "/")
        ip = lan_ip()
        print("\n" + "=" * 70)
        print(f"  On your home Wi-Fi (phone or PC):  http://{ip}:8080")
        print(f"  Public web link:                   {url or 'not available'}")
        if why:
            print(f"    {why}")
        print(f"  Web codes: general {conf['web_code']}, master {conf['master_code']}")
        print("  Close this window to stop PrintWatch.  Settings: PrintWatch.exe --setup")
        print("=" * 70 + "\n", flush=True)
        if url:
            try:
                with open(os.path.join(DATA, "public-link.txt"), "w") as f:
                    f.write(url + "\n")
            except OSError:
                pass

    threading.Thread(target=announce, daemon=True).start()

    os.environ.update(PRINTER_IP=conf["ip"], PRINTER_SERIAL=conf["serial"], ACCESS_CODE=conf["code"],
                      APP_PIN=conf.get("pin", ""), PORT="8080", DATA_DIR=DATA, MODEL_PATH=MODEL,
                      CAMVIEW_OWNER="http://127.0.0.1:8091")
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass
    sys.path.insert(0, HERE)
    from app.main import main as app_main
    app_main()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        input("\nPrintWatch stopped with an error (above). Press Enter to close.")
