"""Controller: tiene insieme camera, monitor, bus eventi e libreria ninna
nanne, e permette al wizard di riconfigurare la camera "a caldo" (senza
riavviare il programma).
"""

from __future__ import annotations

import threading

from .camera import Camera, probe_rtsp
from .config import CameraConfig, Config
from .discovery import find_cameras
from .events import EventBus
from .lullaby import LullabyLibrary
from .monitor import Monitor
from .onvif_ptz import PtzController

# Valori di default segnaposto: se la camera e' ancora cosi', il wizard parte.
_PLACEHOLDER_IP = "192.168.1.100"


class Controller:
    def __init__(self, config: Config):
        self.config = config
        self.bus = EventBus()
        self.library = LullabyLibrary(config.lullaby.directory)
        self.camera: Camera | None = None
        self.monitor: Monitor | None = None
        self.ptz: PtzController | None = None
        self._lock = threading.Lock()
        self._build()

    # ---- costruzione / avvio ------------------------------------------
    def _build(self) -> None:
        self.camera = Camera(self.config.camera.build_url(),
                             transport=self.config.camera.rtsp_transport)
        self.monitor = Monitor(self.config, self.camera, self.bus)
        c = self.config.camera
        self.ptz = PtzController(c.host(), c.username, c.password, c.onvif_port)

    def start(self) -> None:
        self.camera.start()
        self.monitor.start()

    def stop(self) -> None:
        if self.monitor:
            self.monitor.stop()
        if self.camera:
            self.camera.stop()

    # ---- stato configurazione -----------------------------------------
    def is_configured(self) -> bool:
        c = self.config.camera
        if self.config.configured:
            return True
        if c.rtsp_url:
            return True
        return bool(c.ip and c.ip != _PLACEHOLDER_IP)

    # ---- operazioni del wizard ----------------------------------------
    @staticmethod
    def discover() -> list[str]:
        return find_cameras()

    @staticmethod
    def test_camera(cam: CameraConfig) -> dict:
        # Prova automaticamente i percorsi RTSP comuni.
        return probe_rtsp(cam)

    def apply_camera(self, values: dict) -> dict:
        """Applica i nuovi dati della camera, salva e riavvia lo stream."""
        cam = self.config.camera
        cam.ip = str(values.get("ip", cam.ip)).strip()
        cam.rtsp_port = int(values.get("rtsp_port", cam.rtsp_port) or 554)
        cam.username = str(values.get("username", cam.username)).strip()
        if "password" in values:
            cam.password = str(values.get("password") or "")
        cam.stream = str(values.get("stream", cam.stream) or "sub")

        # Se il wizard ha gia' trovato l'URL/trasporto funzionante li usiamo;
        # altrimenti li cerchiamo ora.
        provided = str(values.get("rtsp_url", "") or "")
        if provided:
            cam.rtsp_url = provided
            t = str(values.get("rtsp_transport", "") or "")
            if t in ("tcp", "udp"):
                cam.rtsp_transport = t
        else:
            cam.rtsp_url = ""  # azzera per poter sondare da capo
            found = probe_rtsp(cam)
            cam.rtsp_url = found.get("url", "") or ""
            if found.get("transport") in ("tcp", "udp"):
                cam.rtsp_transport = found["transport"]
        self.config.configured = True

        with self._lock:
            self.stop()
            self.config.save()
            self._build()
            self.start()
        return {"ok": True}

    # ---- PTZ (movimento camera) ---------------------------------------
    def ptz_available(self) -> bool:
        if not self.ptz:
            return False
        ok = self.ptz.is_available()
        # Memorizza la porta ONVIF trovata, cosi' i prossimi avvii sono veloci.
        if ok and self.ptz.port and self.config.camera.onvif_port != self.ptz.port:
            self.config.camera.onvif_port = self.ptz.port
            try:
                self.config.save()
            except Exception:
                pass
        return ok

    def ptz_command(self, action: str) -> bool:
        return bool(self.ptz and self.ptz.move(action))

    def apply_motion(self, values: dict) -> dict:
        m = self.config.motion
        if "sensitivity" in values:
            m.sensitivity = max(1, min(100, int(values["sensitivity"])))
            if self.monitor:
                self.monitor.set_sensitivity(m.sensitivity)
        if "enabled" in values:
            m.enabled = bool(values["enabled"])
            if self.monitor:
                self.monitor.set_enabled(m.enabled)
        self.config.save()
        return {"ok": True}
