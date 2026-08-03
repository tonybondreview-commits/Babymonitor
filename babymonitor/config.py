"""Caricamento della configurazione da file YAML.

I dati sensibili (utente/password della camera) restano solo in locale nel
file config.yaml, che NON viene versionato su git (vedi .gitignore).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from urllib.parse import quote

import yaml

# Percorsi RTSP piu' comuni per le camere Fredi / Yoosee.
# "onvif1" e' di solito lo stream principale (alta qualita'),
# "onvif2" il sottostream (piu' leggero, ideale per il rilevamento).
YOOSEE_RTSP_PATHS = {
    "main": "onvif1",
    "sub": "onvif2",
}


@dataclass
class CameraConfig:
    ip: str = "192.168.1.100"
    rtsp_port: int = 554
    username: str = "admin"
    password: str = ""
    # Se valorizzato, ha priorita' e viene usato cosi' com'e'.
    rtsp_url: str = ""
    # "sub" e' consigliato per l'analisi: meno banda, stessa efficacia.
    stream: str = "sub"
    # Trasporto RTSP: "tcp" o "udp" (alcune camere accettano solo UDP).
    # Il wizard lo determina da solo durante la prova di collegamento.
    rtsp_transport: str = "tcp"

    def host(self) -> str:
        """Solo l'indirizzo, senza eventuale porta digitata per errore.

        Se l'utente scrive "192.168.1.67:5000" (la porta ONVIF), la porta va
        ignorata: per RTSP usiamo self.rtsp_port (554).
        """
        h = self.ip.strip().split("/")[0]
        if h.count(":") == 1:  # host:porta (non IPv6)
            h = h.split(":")[0]
        return h

    def url_for_path(self, path: str, with_credentials: bool = True) -> str:
        """Costruisce l'URL RTSP per un percorso specifico.

        Alcune camere vogliono le credenziali nell'URL, altre no: il wizard
        prova entrambe le varianti (with_credentials True/False).
        """
        auth = ""
        if with_credentials and self.username:
            user = quote(self.username, safe="")
            pwd = quote(self.password, safe="")
            auth = f"{user}:{pwd}@"
        return f"rtsp://{auth}{self.host()}:{self.rtsp_port}/{path.lstrip('/')}"

    def build_url(self) -> str:
        """Costruisce l'URL RTSP completo."""
        if self.rtsp_url:
            return self.rtsp_url
        path = YOOSEE_RTSP_PATHS.get(self.stream, YOOSEE_RTSP_PATHS["sub"])
        return self.url_for_path(path)


@dataclass
class MotionConfig:
    enabled: bool = True
    sensitivity: int = 55          # 1..100
    cooldown_seconds: float = 15.0  # attesa minima tra due allarmi
    consecutive_frames: int = 3     # fotogrammi consecutivi per confermare
    warmup_frames: int = 20         # fotogrammi iniziali per stabilizzare il fondo


@dataclass
class LullabyConfig:
    directory: str = "lullabies"
    # Dove riprodurre di default: "browser" (dispositivo vicino al bimbo),
    # "local" (altoparlante del cervello), "camera" (altoparlante della camera).
    default_target: str = "browser"


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    motion: MotionConfig = field(default_factory=MotionConfig)
    lullaby: LullabyConfig = field(default_factory=LullabyConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    # True quando l'utente ha completato il wizard di configurazione.
    configured: bool = False

    # Percorso del file da cui e' stata caricata (per il salvataggio).
    _path: str = field(default="config.yaml", repr=False)

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        data: dict = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        cfg = cls(
            camera=CameraConfig(**(data.get("camera") or {})),
            motion=MotionConfig(**(data.get("motion") or {})),
            lullaby=LullabyConfig(**(data.get("lullaby") or {})),
            server=ServerConfig(**(data.get("server") or {})),
            configured=bool(data.get("configured", False)),
        )
        cfg._path = path
        # La password puo' arrivare anche da variabile d'ambiente,
        # cosi' non serve scriverla nel file.
        env_pwd = os.environ.get("CAMERA_PASSWORD")
        if env_pwd:
            cfg.camera.password = env_pwd
        return cfg

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_path", None)
        return d

    def save(self, path: str | None = None) -> None:
        """Salva la configurazione su file YAML (usato dal wizard)."""
        target = path or self._path
        with open(target, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, allow_unicode=True, sort_keys=False)
        self._path = target
