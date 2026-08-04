"""Audio della camera in formato HLS (per iPad/Safari, che lo riproduce sempre).

Un solo processo ffmpeg estrae l'audio dallo stream RTSP e scrive un flusso
HLS (playlist .m3u8 + segmenti .ts) in una cartella temporanea. La webapp lo
riproduce con un elemento <audio> puntato alla playlist.

Il processo parte alla prima richiesta e si ferma da solo dopo un po' di
inattivita' (nessuno che ascolta), per non tenere occupata la camera.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
import threading
import time


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


class HlsAudio:
    def __init__(self, url_getter, transport_getter, idle_timeout: float = 20.0):
        self._url = url_getter
        self._transport = transport_getter
        self.idle_timeout = idle_timeout
        self.dir = os.path.join(tempfile.gettempdir(), "babymonitor_hls")
        os.makedirs(self.dir, exist_ok=True)
        self._proc: subprocess.Popen | None = None
        self._last_access = 0.0
        self._lock = threading.Lock()
        self._reaper: threading.Thread | None = None

    def _cmd(self) -> list[str]:
        return [
            _ffmpeg(), "-nostdin", "-rtsp_transport", self._transport(),
            "-fflags", "nobuffer", "-i", self._url(),
            "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "64k",
            "-f", "hls", "-hls_time", "1", "-hls_list_size", "4",
            "-hls_flags", "delete_segments+omit_endlist",
            "-hls_segment_type", "mpegts",
            "-hls_segment_filename", "seg_%d.ts", "audio.m3u8",
            "-loglevel", "error",
        ]

    def _running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ensure(self) -> None:
        """Avvia ffmpeg HLS se non e' gia' in esecuzione."""
        with self._lock:
            self._last_access = time.time()
            if self._running():
                return
            # pulisci i vecchi segmenti
            for f in glob.glob(os.path.join(self.dir, "*.ts")) + glob.glob(os.path.join(self.dir, "*.m3u8")):
                try:
                    os.remove(f)
                except OSError:
                    pass
            try:
                self._proc = subprocess.Popen(self._cmd(), cwd=self.dir,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                self._proc = None
                return
            if not self._reaper or not self._reaper.is_alive():
                self._reaper = threading.Thread(target=self._reap, name="hls-reaper", daemon=True)
                self._reaper.start()

    def touch(self) -> None:
        self._last_access = time.time()

    def wait_for_playlist(self, timeout: float = 5.0) -> str | None:
        """Attende che la playlist esista e abbia almeno un segmento."""
        path = os.path.join(self.dir, "audio.m3u8")
        end = time.time() + timeout
        while time.time() < end:
            if os.path.exists(path) and glob.glob(os.path.join(self.dir, "seg_*.ts")):
                return path
            time.sleep(0.2)
        return None

    def file(self, name: str) -> str | None:
        """Percorso sicuro di un file HLS (solo .ts/.m3u8 dentro la cartella)."""
        safe = os.path.basename(name)
        if not (safe.endswith(".ts") or safe.endswith(".m3u8")):
            return None
        full = os.path.join(self.dir, safe)
        return full if os.path.isfile(full) else None

    def stop(self) -> None:
        with self._lock:
            if self._running():
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=3)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
            self._proc = None

    def _reap(self) -> None:
        while True:
            time.sleep(3)
            if not self._running():
                return
            if time.time() - self._last_access > self.idle_timeout:
                self.stop()
                return
