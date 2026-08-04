"""Invio audio VERSO l'altoparlante della camera (ONVIF backchannel via RTSP).

Sperimentale: negozia una sessione RTSP con l'header ONVIF backchannel, poi
spedisce l'audio (convertito in G.711 con ffmpeg) come pacchetti RTP
interlacciati sulla stessa connessione TCP. Non tutte le camere lo accettano.

Flusso: OPTIONS -> DESCRIBE(backchannel) -> [parse SDP] -> SETUP(TCP) ->
RECORD -> invio RTP.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from urllib.parse import urlparse


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


class Backchannel:
    def __init__(self, rtsp_url: str):
        p = urlparse(rtsp_url)
        self.user = p.username or ""
        self.password = p.password or ""
        self.host = p.hostname or ""
        self.port = p.port or 554
        path = p.path or "/"
        self.base_url = f"rtsp://{self.host}:{self.port}{path}"
        self.sock: socket.socket | None = None
        self.cseq = 0
        self.realm = ""
        self.nonce = ""
        self.session = ""
        self._stop = False
        self._proc: subprocess.Popen | None = None

    # ---- RTSP di base --------------------------------------------------
    def _auth(self, method: str, uri: str) -> str:
        if not (self.realm and self.nonce and self.user):
            return ""
        ha1 = _md5(f"{self.user}:{self.realm}:{self.password}")
        ha2 = _md5(f"{method}:{uri}")
        resp = _md5(f"{ha1}:{self.nonce}:{ha2}")
        return (f'Authorization: Digest username="{self.user}", realm="{self.realm}", '
                f'nonce="{self.nonce}", uri="{uri}", response="{resp}"\r\n')

    def _request(self, method: str, uri: str, extra: str = "") -> tuple[int, dict, str]:
        self.cseq += 1
        req = f"{method} {uri} RTSP/1.0\r\nCSeq: {self.cseq}\r\n"
        req += self._auth(method, uri)
        if self.session:
            req += f"Session: {self.session}\r\n"
        req += extra + "\r\n"
        self.sock.sendall(req.encode())
        return self._read()

    def _read(self) -> tuple[int, dict, str]:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode(errors="ignore").split("\r\n")
        status = 0
        if lines and lines[0].startswith("RTSP/"):
            try:
                status = int(lines[0].split()[1])
            except (IndexError, ValueError):
                status = 0
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        # aggiorna realm/nonce da WWW-Authenticate
        wa = headers.get("www-authenticate", "")
        if "digest" in wa.lower():
            m = re.search(r'realm="([^"]+)"', wa)
            n = re.search(r'nonce="([^"]+)"', wa)
            if m:
                self.realm = m.group(1)
            if n:
                self.nonce = n.group(1)
        if "session" in headers:
            self.session = headers["session"].split(";")[0].strip()
        body = rest
        clen = int(headers.get("content-length", 0) or 0)
        while len(body) < clen:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            body += chunk
        return status, headers, body.decode(errors="ignore")

    def _request_auth(self, method: str, uri: str, extra: str = "") -> tuple[int, dict, str]:
        """Come _request, ma se riceve 401 riprova con l'autenticazione."""
        status, headers, body = self._request(method, uri, extra)
        if status == 401:
            status, headers, body = self._request(method, uri, extra)
        return status, headers, body

    # ---- SDP -----------------------------------------------------------
    def _pick_backchannel(self, sdp: str) -> tuple[str, int, str]:
        """Trova la traccia audio del backchannel: (control_url, payload, codec)."""
        blocks = ("\n" + sdp).split("\nm=")
        best = None
        for b in blocks[1:]:
            if not b.startswith("audio"):
                continue
            first = b.splitlines()[0]  # "audio 0 RTP/AVP 0"
            parts = first.split()
            pt = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            ctrl = ""
            mc = re.search(r"a=control:(\S+)", b)
            if mc:
                ctrl = mc.group(1)
            codec = "mulaw"
            rm = re.search(r"a=rtpmap:%d\s+(\S+)" % pt, b)
            if rm and "PCMA" in rm.group(1).upper():
                codec = "alaw"
            is_back = ("sendonly" in b) or ("backchannel" in b.lower())
            cand = (ctrl, pt, codec, is_back)
            if is_back:
                best = cand
                break
            if best is None:
                best = cand
        if not best:
            return "", 0, ""
        ctrl, pt, codec, _ = best
        if ctrl in ("", "*"):
            ctrl = self.base_url
        elif not ctrl.startswith("rtsp://"):
            ctrl = self.base_url.rstrip("/") + "/" + ctrl.lstrip("/")
        return ctrl, pt, codec

    # ---- invio ---------------------------------------------------------
    def stop(self) -> None:
        self._stop = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def send_file(self, filepath: str, timeout: float = 8.0) -> dict:
        """Negozia il backchannel e invia il file audio. Ritorna {ok, error}."""
        self._stop = False
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
            self.sock.settimeout(timeout)
        except OSError as e:
            return {"ok": False, "error": f"connessione RTSP fallita: {e}"}

        try:
            self._request_auth("OPTIONS", self.base_url)
            back = "Require: www.onvif.org/ver20/backchannel\r\nAccept: application/sdp\r\n"
            st, _, sdp = self._request_auth("DESCRIBE", self.base_url, back)
            if st != 200 or "m=audio" not in sdp:
                return {"ok": False, "error": f"DESCRIBE senza audio backchannel (stato {st})"}
            ctrl, pt, codec = self._pick_backchannel(sdp)
            if not ctrl:
                return {"ok": False, "error": "nessuna traccia audio nel SDP"}

            transport = "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n"
            st, _, _ = self._request_auth("SETUP", ctrl, transport)
            if st != 200:
                return {"ok": False, "error": f"SETUP rifiutato (stato {st})"}

            st, _, _ = self._request_auth("RECORD", self.base_url,
                                          "Range: npt=0.000-\r\n")
            if st not in (200, 0):
                return {"ok": False, "error": f"RECORD rifiutato (stato {st})"}

            self._stream(filepath, pt, codec)
            return {"ok": True, "error": ""}
        except Exception as e:  # pragma: no cover
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            try:
                if self.session:
                    self._request("TEARDOWN", self.base_url)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass

    def _stream(self, filepath: str, pt: int, codec: str) -> None:
        fmt = "mulaw" if codec == "mulaw" else "alaw"
        cmd = [_ffmpeg(), "-nostdin", "-re", "-i", filepath, "-vn",
               "-ar", "8000", "-ac", "1", "-f", fmt, "pipe:1", "-loglevel", "error"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        seq = 0
        ts = 0
        ssrc = 0x13579BDF
        marker = 0x80
        samples = 160  # 20ms di G.711 a 8kHz
        while not self._stop:
            payload = self._proc.stdout.read(samples)
            if not payload:
                break
            b1 = pt | (marker if seq == 0 else 0)
            rtp = struct.pack(">BBHII", 0x80, b1 & 0xFF, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc) + payload
            frame = b"$" + bytes([0]) + struct.pack(">H", len(rtp)) + rtp
            try:
                self.sock.sendall(frame)
            except OSError:
                break
            seq = (seq + 1) & 0xFFFF
            ts = (ts + samples) & 0xFFFFFFFF

        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
