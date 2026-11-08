"""Direct phone <-> Pi access from anywhere. No VPN app, no relay, no cloud.

* A second listener (default TCP 8443) serves the same API over HTTPS with the
  Pi's own self-signed certificate. The phone app pins that certificate, so a
  man-in-the-middle can't impersonate the Pi.
* Every request on that port needs a device key. Phones get one by pairing
  while on your home Wi-Fi (the LAN port), so only phones that have been
  inside your house can ever connect.
* UPnP asks your router to forward the port and reports your public IP, so
  usually nothing has to be configured by hand.
"""
import datetime
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

log = logging.getLogger("remote")


# ------------------------------------------------------------------ certificate
def ensure_cert(data_dir):
    crt, key = os.path.join(data_dir, "remote.crt"), os.path.join(data_dir, "remote.key")
    if not (os.path.exists(crt) and os.path.exists(key)):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        k = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PrintWatch")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=3650))
                .sign(k, hashes.SHA256()))
        old = os.umask(0o077)
        try:
            with open(key, "wb") as f:
                f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
            with open(crt, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
        finally:
            os.umask(old)
        log.info("generated remote-access certificate")
    import ssl
    with open(crt) as f:
        der = ssl.PEM_cert_to_DER_cert(f.read())
    return crt, key, hashlib.sha256(der).hexdigest()


# ------------------------------------------------------------------ device keys
class Devices:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        try:
            with open(path) as f:
                self.items = json.load(f)
        except (OSError, ValueError):
            self.items = []

    def _save(self):
        tmp = self.path + ".tmp"
        old = os.umask(0o077)
        try:
            with open(tmp, "w") as f:
                json.dump(self.items, f)
        finally:
            os.umask(old)
        os.replace(tmp, self.path)

    @staticmethod
    def _h(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def pair(self, name):
        token = secrets.token_urlsafe(32)
        with self._lock:
            self.items.append({"id": secrets.token_hex(4), "name": (name or "phone")[:40],
                               "hash": self._h(token), "created": int(time.time()), "last_seen": None})
            self._save()
        return token

    def check(self, token):
        if not token:
            return None
        h = self._h(token)
        with self._lock:
            for d in self.items:
                if hmac.compare_digest(d["hash"], h):
                    if not d["last_seen"] or time.time() - d["last_seen"] > 300:
                        d["last_seen"] = int(time.time())
                        self._save()
                    return d
        return None

    def remove(self, dev_id):
        with self._lock:
            self.items = [d for d in self.items if d["id"] != dev_id]
            self._save()

    def public(self):
        return [{k: d[k] for k in ("id", "name", "created", "last_seen")} for d in self.items]


class Throttle:
    """Lock out an address after repeated bad keys."""

    def __init__(self, max_fail=10, window=600, block=3600):
        self.fails, self.blocked = {}, {}
        self.max_fail, self.window, self.block = max_fail, window, block

    def is_blocked(self, ip):
        until = self.blocked.get(ip)
        return bool(until and until > time.time())

    def fail(self, ip):
        now = time.time()
        lst = [t for t in self.fails.get(ip, []) if now - t < self.window] + [now]
        self.fails[ip] = lst
        if len(lst) >= self.max_fail:
            self.blocked[ip] = now + self.block
            log.warning("blocking %s for %ds after %d bad keys", ip, self.block, len(lst))


def is_private(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_loopback or a.is_link_local
    except ValueError:
        return False


# ------------------------------------------------------------------ UPnP
SSDP = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
        "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n")
SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2", "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANPPPConnection:1")


class UPnP:
    def __init__(self, port, lan_ip_hint=None):
        self.port = port
        self.lan_ip = lan_ip_hint
        self.control = self.service = None
        self.external_ip = None
        self.mapped = False
        self.error = None
        self.checked = 0

    def _discover(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.settimeout(3)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        try:
            s.sendto(SSDP.encode(), ("239.255.255.250", 1900))
            while True:
                data, addr = s.recvfrom(4096)
                m = re.search(rb"(?im)^location:\s*(\S+)", data)
                if m:
                    return m.group(1).decode(), addr[0]
        finally:
            s.close()

    def _find_control(self, location):
        xml = urllib.request.urlopen(location, timeout=5).read()
        root = ET.fromstring(xml)
        base = re.match(r"(https?://[^/]+)", location).group(1)
        for svc in root.iter():
            if not svc.tag.endswith("service"):
                continue
            st = next((c.text for c in svc if c.tag.endswith("serviceType")), "")
            if st in SERVICES:
                url = next((c.text for c in svc if c.tag.endswith("controlURL")), "")
                return (url if url.startswith("http") else base + ("" if url.startswith("/") else "/") + url), st
        raise RuntimeError("router has no WAN IP service")

    def _soap(self, action, args):
        body = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
        env = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
               's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
               f'<u:{action} xmlns:u="{self.service}">{body}</u:{action}></s:Body></s:Envelope>')
        req = urllib.request.Request(self.control, data=env.encode(), method="POST", headers={
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{self.service}#{action}"'})
        return urllib.request.urlopen(req, timeout=6).read().decode(errors="replace")

    def refresh(self):
        self.checked = time.time()
        try:
            if not self.control:
                location, router = self._discover()
                self.control, self.service = self._find_control(location)
                if not self.lan_ip:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect((router, 1900))
                    self.lan_ip = s.getsockname()[0]
                    s.close()
            r = self._soap("GetExternalIPAddress", {})
            m = re.search(r"<NewExternalIPAddress>([^<]*)<", r)
            self.external_ip = m.group(1) if m and m.group(1) else None
            self._soap("AddPortMapping", {
                "NewRemoteHost": "", "NewExternalPort": self.port, "NewProtocol": "TCP",
                "NewInternalPort": self.port, "NewInternalClient": self.lan_ip, "NewEnabled": 1,
                "NewPortMappingDescription": "PrintWatch", "NewLeaseDuration": 0})
            self.mapped = True
            self.error = None
            log.info("UPnP: TCP %d -> %s:%d, public IP %s", self.port, self.lan_ip, self.port, self.external_ip)
        except socket.timeout:
            self.mapped, self.error = False, "no UPnP router answered (UPnP is probably off)"
        except Exception as e:  # noqa: BLE001
            self.mapped, self.error = False, f"UPnP: {e}"
            self.control = None
        if self.error:
            log.info(self.error)

    def start(self):
        def loop():
            while True:
                self.refresh()
                time.sleep(1800)
        threading.Thread(target=loop, name="upnp", daemon=True).start()


def cgnat(ip):
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10") or ipaddress.ip_address(ip).is_private
    except ValueError:
        return False
