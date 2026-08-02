"""
yi_camera.py -- control client for the original Xiaomi YI Action Camera (YDXJ).

Talks the camera's TCP JSON protocol on port 7878 (token handshake), and maps
on-camera file paths to the HTTP file server on port 80 for the gallery.
"""

import json
import socket
import threading
from time import sleep

MSG_TOKEN        = 257
MSG_STATUS       = 7
MSG_SET_SETTING  = 2
MSG_GET_SETTINGS = 3
MSG_BATTERY      = 13
MSG_RECORD_START = 513
MSG_RECORD_STOP  = 514
MSG_TAKE_PHOTO   = 769


class YiCameraError(Exception):
    """Raised when the camera reports an error or cannot be reached."""


class YiCamera:
    def __init__(self, ip="192.168.42.1", port=7878, timeout=6):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._sock = None
        self._token = None
        self._buffer = ""
        self._last_status = None
        self._lock = threading.Lock()

    @property
    def connected(self):
        return self._sock is not None and self._token is not None

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        try:
            self._sock.connect((self.ip, self.port))
        except OSError as exc:
            self._sock = None
            raise YiCameraError(
                f"Cannot reach camera at {self.ip}:{self.port}. "
                f"Are you on the YDXJ_ Wi-Fi network? ({exc})"
            )
        self._sock.sendall(json.dumps({"msg_id": MSG_TOKEN, "token": 0}).encode())
        reply = self._read_reply(MSG_TOKEN)
        self._token = reply.get("param")
        if self._token is None:
            raise YiCameraError("Camera did not return a token.")
        return self._token

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._token = None
                self._buffer = ""

    # -- low level I/O --------------------------------------------------------
    def _read_reply(self, expect_msg_id, tries=40):
        self._last_status = None
        for _ in range(tries):
            obj = self._next_json_object()
            if obj is None:
                try:
                    chunk = self._sock.recv(4096).decode("utf-8", "ignore")
                except socket.timeout:
                    break
                if not chunk:
                    break
                self._buffer += chunk
                continue
            if obj.get("msg_id") == MSG_STATUS:
                self._last_status = obj
                continue
            if obj.get("msg_id") == expect_msg_id:
                return obj
        raise YiCameraError(f"No reply for msg_id {expect_msg_id}.")

    def _next_json_object(self):
        self._buffer = self._buffer.lstrip()
        if not self._buffer.startswith("{"):
            brace = self._buffer.find("{")
            if brace == -1:
                self._buffer = ""
                return None
            self._buffer = self._buffer[brace:]
        depth = 0
        for i, ch in enumerate(self._buffer):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw, self._buffer = self._buffer[: i + 1], self._buffer[i + 1 :]
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return None
        return None

    def _command(self, msg_id, **extra):
        if not self.connected:
            raise YiCameraError("Not connected. Call connect() first.")
        with self._lock:
            payload = {"msg_id": msg_id, "token": self._token}
            payload.update(extra)
            self._sock.sendall(json.dumps(payload).encode())
            reply = self._read_reply(msg_id)
            sleep(0.2)
        rval = reply.get("rval", 0)
        if rval != 0:
            raise YiCameraError(f"Camera returned error rval={rval} for msg_id {msg_id}.")
        return reply

    # -- features -------------------------------------------------------------
    def take_photo(self):
        self._command(MSG_TAKE_PHOTO)
        status = self._last_status
        if status and status.get("type") == "photo_taken":
            return status.get("param")
        return None

    def start_recording(self):
        self._command(MSG_RECORD_START)
        return True

    def stop_recording(self):
        self._command(MSG_RECORD_STOP)
        return True

    def battery(self):
        reply = self._command(MSG_BATTERY)
        return {"type": reply.get("type"), "level": reply.get("param")}

    def get_settings(self):
        reply = self._command(MSG_GET_SETTINGS)
        flat = {}
        for item in reply.get("param", []):
            if isinstance(item, dict):
                flat.update(item)
        return flat

    def http_url_for(self, camera_path):
        marker = "/DCIM/"
        idx = camera_path.find(marker)
        if idx != -1:
            return f"http://{self.ip}{camera_path[idx:]}"
        return f"http://{self.ip}/{camera_path.lstrip('/')}"
