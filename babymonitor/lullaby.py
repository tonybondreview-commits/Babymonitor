"""Gestione delle ninna nanne.

Le ninna nanne sono file audio (mp3/wav/ogg/m4a) messi nella cartella
`lullabies/`. La webapp le elenca e le riproduce; il modo piu' affidabile e
completamente offline e' riprodurle nel browser del dispositivo vicino al
bimbo (es. l'iPad sul supporto vicino alla culla).

Questa classe gestisce l'elenco dei file e, opzionalmente, la riproduzione
"local" (altoparlante del cervello) e "camera" (altoparlante della camera via
backchannel ONVIF, best-effort, dipende dal modello).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading

AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}


class LullabyLibrary:
    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def list(self) -> list[dict]:
        """Elenca le ninna nanne disponibili (ordinate per nome)."""
        items = []
        for name in sorted(os.listdir(self.directory)):
            ext = os.path.splitext(name)[1].lower()
            if ext in AUDIO_EXTS:
                items.append({"name": name, "title": os.path.splitext(name)[0]})
        return items

    def path_for(self, name: str) -> str | None:
        """Ritorna il percorso sicuro di un file (evita path traversal)."""
        safe = os.path.basename(name)
        full = os.path.join(self.directory, safe)
        if os.path.isfile(full) and os.path.splitext(safe)[1].lower() in AUDIO_EXTS:
            return full
        return None

    # ---- riproduzione sul "cervello" (opzionale) ----------------------
    @staticmethod
    def _find_player() -> list[str] | None:
        """Trova un lettore da riga di comando disponibile nel sistema."""
        for cmd in (["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
                    ["mpg123", "-q"],
                    ["mpv", "--no-video", "--really-quiet"],
                    ["cvlc", "--play-and-exit", "--quiet"]):
            if shutil.which(cmd[0]):
                return cmd
        return None

    def play_local(self, name: str) -> bool:
        """Riproduce sull'altoparlante del dispositivo-cervello."""
        path = self.path_for(name)
        if not path:
            return False
        player = self._find_player()
        if not player:
            return False
        self.stop_local()
        with self._lock:
            self._proc = subprocess.Popen(
                player + [path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True

    def stop_local(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None
