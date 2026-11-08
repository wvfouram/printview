"""Bambu P1-series LAN camera client.

The P1S does not speak RTSP. In LAN mode it serves JPEG frames over a TLS
socket on port 6000: you send an 80-byte auth packet, then it streams
[16-byte header (first 4 bytes = little-endian payload size)][JPEG] forever.
"""
import logging
import socket
import ssl
import struct
import threading
import time

log = logging.getLogger("camera")


class BambuCamera:
    def __init__(self, ip: str, access_code: str, port: int = 6000):
        self.ip = ip
        self.port = port
        self.access_code = access_code
        self.frame: bytes | None = None
        self.frame_id = 0
        self.frame_time = 0.0
        self.connected = False
        self.error: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # public -----------------------------------------------------------
    def start(self):
        threading.Thread(target=self._run, name="camera", daemon=True).start()

    def stop(self):
        self._stop.set()

    def latest(self):
        with self._lock:
            return self.frame, self.frame_id, self.frame_time

    def status(self):
        age = time.time() - self.frame_time if self.frame_time else None
        return {
            "connected": self.connected,
            "frame_age_s": round(age, 1) if age is not None else None,
            "error": self.error,
        }

    # internals --------------------------------------------------------
    def _auth_packet(self) -> bytes:
        return (
            struct.pack("<IIII", 0x40, 0x3000, 0, 0)
            + b"bblp".ljust(32, b"\x00")
            + self.access_code.encode()[:32].ljust(32, b"\x00")
        )

    @staticmethod
    def _recv_exact(sock, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("camera socket closed")
            buf.extend(chunk)
        return bytes(buf)

    def _run(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # printer uses a self-signed cert
        backoff = 2
        while not self._stop.is_set():
            try:
                with socket.create_connection((self.ip, self.port), timeout=10) as raw:
                    with ctx.wrap_socket(raw, server_hostname=self.ip) as s:
                        s.sendall(self._auth_packet())
                        s.settimeout(20)
                        log.info("camera connected to %s:%s", self.ip, self.port)
                        while not self._stop.is_set():
                            header = self._recv_exact(s, 16)
                            size = struct.unpack("<I", header[:4])[0]
                            if size == 0 or size > 8_000_000:
                                raise ValueError(f"bad frame size {size} (wrong access code?)")
                            data = self._recv_exact(s, size)
                            if data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
                                continue  # not a complete JPEG, skip
                            with self._lock:
                                self.frame = data
                                self.frame_id += 1
                                self.frame_time = time.time()
                            self.connected = True
                            self.error = None
                            backoff = 2
            except Exception as e:  # noqa: BLE001 - keep retrying forever
                if self.connected or self.error != str(e):
                    log.warning("camera: %s", e)
                self.connected = False
                self.error = str(e) or e.__class__.__name__
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30)
