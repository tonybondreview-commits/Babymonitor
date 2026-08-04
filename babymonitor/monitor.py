"""Loop di monitoraggio: legge i fotogrammi dalla camera, rileva il movimento
e pubblica gli eventi sul bus (che la webapp riceve in tempo reale).
"""

from __future__ import annotations

import threading
import time

from .camera import Camera
from .config import Config
from .events import EventBus
from .motion import MotionDetector


class Monitor:
    def __init__(self, config: Config, camera: Camera, bus: EventBus):
        self.config = config
        self.camera = camera
        self.bus = bus
        self.detector = MotionDetector(
            sensitivity=config.motion.sensitivity,
            cooldown=config.motion.cooldown_seconds,
            consec_frames=config.motion.consecutive_frames,
            warmup_frames=config.motion.warmup_frames,
        )
        self._thread: threading.Thread | None = None
        self._running = False
        self.motion_enabled = config.motion.enabled

        # Stato esposto alla webapp.
        self.last_ratio = 0.0
        self.active = False
        self.motion_count = 0
        self._last_active = False
        self._last_connected = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def set_enabled(self, enabled: bool) -> None:
        self.motion_enabled = enabled
        if not enabled:
            self.detector.reset()
            self.active = False
        self.bus.publish("status", self.status())

    def set_sensitivity(self, sensitivity: int) -> None:
        self.config.motion.sensitivity = sensitivity
        self.detector = MotionDetector(
            sensitivity=sensitivity,
            cooldown=self.config.motion.cooldown_seconds,
            consec_frames=self.config.motion.consecutive_frames,
            warmup_frames=self.config.motion.warmup_frames,
        )
        self.bus.publish("status", self.status())

    def status(self) -> dict:
        return {
            "connected": self.camera.connected,
            "motion_enabled": self.motion_enabled,
            "active": self.active,
            "sensitivity": self.config.motion.sensitivity,
            "motion_count": self.motion_count,
            "last_ratio": round(self.last_ratio, 4),
        }

    def _loop(self) -> None:
        last_id = -1
        while self._running:
            # Segnala subito alla webapp quando la camera si connette/disconnette.
            conn = self.camera.connected
            if conn != self._last_connected:
                self._last_connected = conn
                self.bus.publish("status", self.status())

            frame_id, gray = self.camera.read_gray()
            if gray is None or frame_id == last_id:
                time.sleep(0.05)
                continue
            last_id = frame_id

            if not self.motion_enabled:
                continue

            result = self.detector.update(gray)
            self.last_ratio = result.ratio
            self.active = result.active

            if result.motion:
                self.motion_count += 1
                self.bus.publish("motion", {
                    "count": self.motion_count,
                    "ratio": round(result.ratio, 4),
                })

            # Pubblica in tempo reale l'inizio/fine del movimento, cosi' la
            # webapp mostra subito il simbolo e fa il beep (senza attese).
            if result.active != self._last_active:
                self._last_active = result.active
                self.bus.publish("motion_state", {
                    "active": result.active,
                    "count": self.motion_count,
                })
