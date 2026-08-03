"""Collegamento alla camera via RTSP e produzione dei fotogrammi.

Usa OpenCV per aprire lo stream RTSP della camera Fredi/Yoosee. Espone:
  - i fotogrammi grezzi (per l'analisi del movimento)
  - l'ultimo fotogramma codificato in JPEG (per lo streaming MJPEG al browser)

La lettura avviene in un thread dedicato, cosi' il resto dell'app non si
blocca mai in attesa della rete.
"""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np


class Camera:
    def __init__(self, rtsp_url: str, target_width: int = 480, reconnect_delay: float = 3.0):
        self.rtsp_url = rtsp_url
        self.target_width = target_width
        self.reconnect_delay = reconnect_delay

        self._cap: cv2.VideoCapture | None = None
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
        if self._thread:
            self._thread.join(timeout=5)
        if self._cap:
            self._cap.release()

    @property
    def connected(self) -> bool:
        return self._connected

    # ---- accesso ai fotogrammi ----------------------------------------
    def read_gray(self) -> tuple[int, np.ndarray | None]:
        """Ritorna (frame_id, fotogramma in scala di grigi) dell'ultimo frame."""
        with self._lock:
            return self._frame_id, self._latest_gray

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def wait_for_frame(self, last_id: int, timeout: float = 1.0) -> int:
        """Attende un nuovo fotogramma rispetto a last_id (per MJPEG)."""
        with self._new_frame:
            self._new_frame.wait_for(lambda: self._frame_id != last_id, timeout=timeout)
            return self._frame_id

    # ---- thread interno ------------------------------------------------
    def _open(self) -> bool:
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        # Buffer piccolo -> meno latenza (mostriamo il "quasi live").
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if not cap.isOpened():
            cap.release()
            return False
        self._cap = cap
        return True

    def _loop(self) -> None:
        while self._running:
            if self._cap is None and not self._open():
                self._connected = False
                time.sleep(self.reconnect_delay)
                continue

            ok, frame = self._cap.read()
            if not ok or frame is None:
                # Connessione persa: chiudo e riprovo.
                self._connected = False
                self._cap.release()
                self._cap = None
                time.sleep(self.reconnect_delay)
                continue

            self._connected = True
            self._process(frame)

    def _process(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        if w > self.target_width:
            scale = self.target_width / float(w)
            frame = cv2.resize(frame, (self.target_width, int(h * scale)))

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        jpeg = buf.tobytes() if ok else None

        with self._lock:
            self._latest_gray = gray
            if jpeg is not None:
                self._latest_jpeg = jpeg
            self._frame_id += 1
        with self._new_frame:
            self._new_frame.notify_all()
