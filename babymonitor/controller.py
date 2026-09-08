"""Controller: tiene insieme camera, monitor, bus eventi e libreria ninna
nanne, e permette al wizard di riconfigurare la camera "a caldo" (senza
riavviare il programma).
"""

from __future__ import annotations

import threading
import time

from .backchannel import Backchannel
from .camera import Camera, probe_rtsp, quality_preset, test_rtsp, QUALITY_PRESETS
from .config import CameraConfig, Config
from .discovery import find_cameras, scan_subnet
from .events import EventBus
from .hls_audio import HlsAudio
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
        self._audio_available: bool | None = None
        self._lock = threading.Lock()
        self._health: threading.Thread | None = None
        self._running_health = False
        self._bc: Backchannel | None = None
        self.hls = HlsAudio(lambda: self.config.camera.build_url(),
                            lambda: self.config.camera.rtsp_transport)
        self._build()

    # ---- costruzione / avvio ------------------------------------------
    def _build(self) -> None:
        q = quality_preset(self.config.camera.video_quality)
        self.camera = Camera(self.config.camera.build_url(),
                             transport=self.config.camera.rtsp_transport,
                             target_width=q["width"], fps=q["fps"], jpeg_q=q["q"])
        self.monitor = Monitor(self.config, self.camera, self.bus)
        c = self.config.camera
        self.ptz = PtzController(c.host(), c.username, c.password, c.onvif_port)
        self._audio_available = None  # ricontrolla la presenza audio

    def start(self) -> None:
        self.camera.start()
        self.monitor.start()
        # Controllo di salute: se la camera resta irraggiungibile, prova a
        # ritrovarla (utile se dopo un riavvio ha preso un IP diverso).
        if self._health is None or not self._health.is_alive():
            self._running_health = True
            self._health = threading.Thread(target=self._health_loop, name="health", daemon=True)
            self._health.start()

    def stop(self) -> None:
        self._running_health = False
        if self.monitor:
            self.monitor.stop()
        if self.camera:
            self.camera.stop()

    def _rebuild_streams(self) -> None:
        """Ricrea e riavvia camera+monitor senza toccare il thread di salute."""
        if self.monitor:
            self.monitor.stop()
        if self.camera:
            self.camera.stop()
        self._build()
        self.camera.start()
        self.monitor.start()

    def _health_loop(self) -> None:
        down_since: float | None = None
        while self._running_health:
            time.sleep(8)
            if not self.camera or self.camera.connected:
                down_since = None
                continue
            if down_since is None:
                down_since = time.time()
                continue
            if time.time() - down_since < 20:
                continue  # dai tempo alla camera di ripartire sullo stesso IP
            if self._try_rediscover():
                down_since = None

    def _try_rediscover(self) -> bool:
        """Cerca la camera a un nuovo IP (stesso utente/percorso) e si ricollega."""
        cam = self.config.camera
        if not cam.rtsp_url:
            return False
        current = cam.host()
        hosts = scan_subnet(554, timeout=0.4)
        if current in hosts:
            return False  # l'IP c'e' ancora: e' la camera che sta ripartendo
        for h in hosts:
            new_url = cam.rtsp_url.replace(current, h)
            if new_url == cam.rtsp_url:
                continue
            if test_rtsp(new_url, transport=cam.rtsp_transport, timeout=6).get("ok"):
                cam.ip = h
                cam.rtsp_url = new_url
                try:
                    self.config.save()
                except Exception:
                    pass
                with self._lock:
                    self._rebuild_streams()
                self.bus.publish("status", self.monitor.status())
                return True
        return False

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
        raw_ip = str(values.get("ip", cam.ip)).strip()
        # Se l'utente scrive host:porta, quella e' la porta ONVIF (per il PTZ).
        if raw_ip.count(":") == 1 and "/" not in raw_ip:
            _, _, port_part = raw_ip.partition(":")
            if port_part.isdigit():
                cam.onvif_port = int(port_part)
        cam.ip = raw_ip
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

    def ptz_diagnose(self) -> dict:
        """Diagnostica dettagliata del PTZ (perche' il joystick non compare)."""
        if not self.ptz:
            return {"available": False, "hint": "PTZ non inizializzato."}
        return self.ptz.diagnose()

    # ---- audio dalla camera -------------------------------------------
    def audio_available(self) -> bool:
        if self._audio_available is None:
            from .audio import has_audio
            cam = self.config.camera
            self._audio_available = has_audio(cam.build_url(), cam.rtsp_transport)
        return self._audio_available

    def restart_camera(self) -> None:
        """Riavvia il collegamento alla camera (refresh dello stream)."""
        if self.camera:
            self.camera.restart()

    def set_quality(self, quality: str) -> bool:
        """Cambia la qualità video e riavvia lo stream."""
        if quality not in QUALITY_PRESETS:
            return False
        self.config.camera.video_quality = quality
        with self._lock:
            try:
                self.config.save()
            except Exception:
                pass
            self._rebuild_streams()
        return True

    # ---- invio audio alla camera (backchannel, sperimentale) ----------
    def play_to_camera(self, name: str) -> dict:
        path = self.library.path_for(name)
        if not path:
            return {"ok": False, "error": "ninna nanna non trovata"}
        self.stop_to_camera()
        self._bc = Backchannel(self.config.camera.build_url())

        def run():
            result = self._bc.send_file(path)
            self.bus.publish("backchannel", result)

        threading.Thread(target=run, name="backchannel", daemon=True).start()
        return {"ok": True, "started": True}

    def stop_to_camera(self) -> None:
        if self._bc:
            self._bc.stop()

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
