"""Collegamento alla camera via RTSP e produzione dei fotogrammi.

Usa **ffmpeg** (non OpenCV) per leggere lo stream RTSP della camera Fredi/Yoosee
e produrre un flusso MJPEG. Da ogni fotogramma JPEG:
  - serviamo direttamente i byte JPEG al browser (streaming MJPEG);
  - con **Pillow** lo decodifichiamo in scala di grigi per l'analisi del movimento.

Perche' ffmpeg e non OpenCV? Su Android/Termux il pacchetto OpenCV non e' piu'
disponibile in modo affidabile, mentre ffmpeg c'e' sempre. ffmpeg + Pillow
funzionano identici su Raspberry Pi, PC e telefono.

La lettura avviene in un thread dedicato, con riconnessione automatica.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import threading
import time

import numpy as np
from PIL import Image, ImageFilter

_SOI = b"\xff\xd8"  # inizio di un fotogramma JPEG
_EOI = b"\xff\xd9"  # fine di un fotogramma JPEG


# Preset di qualità video: larghezza, fotogrammi/sec e qualità JPEG (q:v basso
# = più nitido). "Alta" usa piena definizione dello stream principale.
QUALITY_PRESETS = {
    "low":    {"width": 320, "fps": 6,  "q": 9},
    "medium": {"width": 480, "fps": 8,  "q": 7},
    "high":   {"width": 960, "fps": 12, "q": 4},
}


def quality_preset(name: str) -> dict:
    return QUALITY_PRESETS.get(name, QUALITY_PRESETS["medium"])


def _ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def split_jpegs(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Estrae i fotogrammi JPEG completi da un buffer MJPEG.

    Ritorna (lista_di_jpeg_completi, resto_del_buffer_ancora_incompleto).
    """
    frames: list[bytes] = []
    while True:
        start = buffer.find(_SOI)
        if start < 0:
            if len(buffer) > 4_000_000:
                buffer = b""  # sicurezza anti-crescita se non troviamo l'inizio
            break
        end = buffer.find(_EOI, start + 2)
        if end < 0:
            if start > 0:
                buffer = buffer[start:]
            break
        frames.append(buffer[start:end + 2])
        buffer = buffer[end + 2:]
    return frames, buffer


# Percorsi RTSP piu' comuni sulle camere ONVIF economiche (Fredi/Yoosee e
# cloni). Il wizard li prova in ordine finche' uno funziona.
CANDIDATE_PATHS = [
    "onvif1", "onvif2",
    "11", "12",
    "live/ch0", "live/ch1", "live/ch00_0", "live/ch01_0",
    "media/video1", "media/video2",
    "h264", "h264_stream", "stream1", "stream2",
    "cam/realmonitor?channel=1&subtype=0",
    "cam/realmonitor?channel=1&subtype=1",
    "ch0_0.h264", "ch0_1.h264",
    "video1", "1", "0",
]

# Errori che indicano "camera irraggiungibile": inutile insistere.
_NET_HINTS = ("no route to host", "timeout", "refused", "unreachable",
              "ffmpeg non installato")


def _is_net_error(err: str) -> bool:
    return any(k in err.lower() for k in _NET_HINTS)


def _is_auth_error(err: str) -> bool:
    e = err.lower()
    return "401" in e or "unauthorized" in e


TRANSPORTS = ("tcp", "udp")  # alcune camere accettano solo UDP


def probe_rtsp(cam, timeout_each: float = 6.0) -> dict:
    """Trova la combinazione RTSP che funziona provando: percorsi comuni ×
    trasporto (TCP/UDP) × con o senza credenziali.

    `cam` e' un CameraConfig. Ritorna {"ok", "url", "path", "transport", "error"}.
    Si ferma subito se la camera e' irraggiungibile.
    """
    if getattr(cam, "rtsp_url", ""):
        for transport in TRANSPORTS:
            r = test_rtsp(cam.rtsp_url, timeout=timeout_each + 3, transport=transport)
            if r["ok"]:
                return {"ok": True, "url": cam.rtsp_url, "path": "",
                        "transport": transport, "error": ""}
            if _is_net_error(r.get("error", "")):
                break
        return {"ok": False, "url": "", "path": "", "transport": "",
                "error": r.get("error", "")}

    last_err = ""
    saw_auth = False
    for path in CANDIDATE_PATHS:
        for transport in TRANSPORTS:
            for with_creds in (True, False):
                url = cam.url_for_path(path, with_credentials=with_creds)
                r = test_rtsp(url, timeout=timeout_each, transport=transport)
                if r["ok"]:
                    return {"ok": True, "url": url, "path": path,
                            "transport": transport, "error": ""}
                err = r.get("error", "")
                last_err = err
                if _is_net_error(err):
                    return {"ok": False, "url": "", "path": "",
                            "transport": "", "error": err}
                if _is_auth_error(err):
                    saw_auth = True
                    continue          # riprova senza credenziali, stesso trasporto
                break                 # 404 / trasporto errato: passa al trasporto dopo
    if saw_auth and _is_auth_error(last_err):
        last_err = "utente/password rifiutati dalla camera"
    return {"ok": False, "url": "", "path": "", "transport": "",
            "error": last_err or "nessun percorso video valido trovato"}


def test_rtsp(url: str, timeout: float = 12.0, transport: str = "tcp") -> dict:
    """Prova a leggere un fotogramma dallo stream RTSP.

    `transport` e' "tcp" o "udp": alcune camere accettano solo uno dei due.
    Ritorna {"ok": bool, "error": str}.
    """
    cmd = [
        _ffmpeg_bin(), "-nostdin", "-rtsp_transport", transport, "-i", url,
        "-an", "-frames:v", "1", "-f", "mjpeg", "pipe:1", "-loglevel", "error",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout: la camera non risponde"}
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg non installato"}
    if p.returncode == 0 and p.stdout[:2] == _SOI:
        return {"ok": True, "error": ""}
    err = (p.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
    return {"ok": False, "error": err[-1] if err else "collegamento non riuscito"}


class Camera:
    def __init__(self, rtsp_url: str, transport: str = "tcp", target_width: int = 480,
                 motion_width: int = 320, fps: int = 8, jpeg_q: int = 7,
                 reconnect_delay: float = 3.0):
        self.rtsp_url = rtsp_url
        self.transport = transport if transport in TRANSPORTS else "tcp"
        self.jpeg_q = jpeg_q                  # qualità JPEG (q:v ffmpeg)
        self.target_width = target_width      # larghezza del video mostrato
        self.motion_width = motion_width      # larghezza usata per l'analisi
        self.fps = fps
        self.reconnect_delay = reconnect_delay

        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

        self._latest_gray: np.ndarray | None = None
        self._latest_jpeg: bytes | None = None
        self._frame_id = 0
        self._connected = False
        self._new_frame = threading.Condition()

    # ---- ciclo di vita -------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._kill()
        if self._thread:
            self._thread.join(timeout=5)

    def _kill(self) -> None:
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self._proc = None

    @property
    def connected(self) -> bool:
        return self._connected

    # ---- accesso ai fotogrammi ----------------------------------------
    def read_gray(self) -> tuple[int, np.ndarray | None]:
        with self._lock:
            return self._frame_id, self._latest_gray

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def wait_for_frame(self, last_id: int, timeout: float = 1.0) -> int:
        with self._new_frame:
            self._new_frame.wait_for(lambda: self._frame_id != last_id, timeout=timeout)
            return self._frame_id

    # ---- thread interno ------------------------------------------------
    def _spawn(self) -> subprocess.Popen:
        cmd = [
            _ffmpeg_bin(), "-nostdin", "-rtsp_transport", self.transport,
            # Compromesso latenza/fluidita': poco buffer ma il riordino dei
            # pacchetti UDP resta attivo, cosi' il video non va a scatti.
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-i", self.rtsp_url, "-an",
            "-vf", f"fps={self.fps},scale={self.target_width}:-1",
            "-q:v", str(self.jpeg_q), "-flush_packets", "1",
            "-f", "mjpeg", "pipe:1", "-loglevel", "error",
        ]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, bufsize=0)

    def _loop(self) -> None:
        while self._running:
            try:
                self._proc = self._spawn()
            except FileNotFoundError:
                # ffmpeg non installato: non possiamo fare nulla, riproviamo.
                self._connected = False
                time.sleep(self.reconnect_delay)
                continue

            buffer = b""
            last_frame = time.monotonic()
            try:
                while self._running:
                    chunk = self._proc.stdout.read(8192)
                    if not chunk:
                        break  # ffmpeg terminato (camera irraggiungibile): riconnetti
                    buffer += chunk
                    # Estrai tutti i fotogrammi JPEG completi presenti nel buffer.
                    frames, buffer = split_jpegs(buffer)
                    for jpeg in frames:
                        self._process(jpeg)
                        last_frame = time.monotonic()
                    if time.monotonic() - last_frame > 15:
                        break  # nessun fotogramma da troppo tempo: riavvia
            except Exception:
                pass
            finally:
                self._connected = False
                self._kill()

            if self._running:
                time.sleep(self.reconnect_delay)

    def _process(self, jpeg: bytes) -> None:
        with self._lock:
            self._latest_jpeg = jpeg
        try:
            img = Image.open(io.BytesIO(jpeg)).convert("L")
            if img.width > self.motion_width:
                h = max(1, int(img.height * self.motion_width / img.width))
                img = img.resize((self.motion_width, h))
            img = img.filter(ImageFilter.GaussianBlur(2))
            gray = np.asarray(img, dtype=np.uint8)
        except Exception:
            return  # fotogramma corrotto: lo saltiamo
        with self._lock:
            self._latest_gray = gray
            self._frame_id += 1
            self._connected = True
        with self._new_frame:
            self._new_frame.notify_all()
