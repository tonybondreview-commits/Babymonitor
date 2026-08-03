"""Controller: tiene insieme camera, monitor, bus eventi e libreria ninna
nanne, e permette al wizard di riconfigurare la camera "a caldo" (senza
riavviare il programma).
"""

from __future__ import annotations

import threading

from .camera import Camera, test_rtsp
from .config import CameraConfig, Config
from .discovery import discover_cameras
from .events import EventBus
from .lullaby import LullabyLibrary
from .monitor import Monitor

# Valori di default segnaposto: se la camera e' ancora cosi', il wizard parte.
_PLACEHOLDER_IP = "192.168.1.100"


class Controller:
    def __init__(self, config: Config):
        self.config = config
        self.bus = EventBus()
        self.library = LullabyLibrary(config.lullaby.directory)
        self.camera: Camera | None = None
        self.monitor: Monitor | None = None
        self._lock = threading.Lock()
        self._build()

    # ---- costruzione / avvio ------------------------------------------
    def _build(self) -> None:
        self.camera = Camera(self.config.camera.build_url())
        self.monitor = Monitor(self.config, self.camera, self.bus)

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
        return discover_cameras()

    @staticmethod
    def test_camera(cam: CameraConfig) -> dict:
        return test_rtsp(cam.build_url())

    def apply_camera(self, values: dict) -> dict:
        """Applica i nuovi dati della camera, salva e riavvia lo stream."""
        cam = self.config.camera
        cam.ip = str(values.get("ip", cam.ip)).strip()
        cam.rtsp_port = int(values.get("rtsp_port", cam.rtsp_port) or 554)
        cam.username = str(values.get("username", cam.username)).strip()
        if "password" in values:
            cam.password = str(values.get("password") or "")
        cam.stream = str(values.get("stream", cam.stream) or "sub")
        cam.rtsp_url = str(values.get("rtsp_url", cam.rtsp_url) or "")
        self.config.configured = True

        with self._lock:
            self.stop()
            self.config.save()
            self._build()
            self.start()
        return {"ok": True}

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
