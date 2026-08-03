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


def test_rtsp(url: str, timeout: float = 12.0) -> dict:
    """Prova a leggere un fotogramma dallo stream RTSP.

    Ritorna {"ok": bool, "error": str}. Usato dal wizard per verificare
    subito se IP/utente/password sono corretti.
    """
    cmd = [
        _ffmpeg_bin(), "-nostdin", "-rtsp_transport", "tcp", "-i", url,
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
    def __init__(self, rtsp_url: str, target_width: int = 480, motion_width: int = 320,
                 fps: int = 8, reconnect_delay: float = 3.0):
        self.rtsp_url = rtsp_url
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
            _ffmpeg_bin(), "-nostdin", "-rtsp_transport", "tcp",
            "-fflags", "nobuffer",
            "-i", self.rtsp_url, "-an",
            "-vf", f"fps={self.fps},scale={self.target_width}:-1",
            "-f", "mjpeg", "-q:v", "7", "pipe:1", "-loglevel", "error",
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
