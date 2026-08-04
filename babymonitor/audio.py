"""Audio dalla camera: porta il microfono della camera al browser.

La camera trasmette l'audio (di solito G.711) dentro lo stream RTSP. Qui lo
estraiamo con ffmpeg e lo riconvertiamo in MP3 "in diretta", cosi' il browser
puo' riprodurlo con un semplice elemento <audio>. Serve per SENTIRE il bimbo
dal dispositivo che fa da monitor.
"""

from __future__ import annotations

import shutil
import subprocess


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def has_audio(url: str, transport: str = "tcp", timeout: float = 10.0) -> bool:
    """Controlla se lo stream contiene una traccia audio."""
    cmd = [
        _ffprobe(), "-v", "error", "-rtsp_transport", transport,
        "-select_streams", "a", "-show_entries", "stream=codec_name",
        "-of", "default=nk=1:nw=1", url,
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    except OSError:
        return False
    return bool(p.stdout.strip())


def audio_command(url: str, transport: str = "tcp") -> list[str]:
    """Comando ffmpeg: RTSP -> MP3 in streaming continuo (solo audio)."""
    return [
        _ffmpeg(), "-nostdin", "-rtsp_transport", transport,
        "-fflags", "nobuffer", "-i", url,
        "-vn", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k",
        "-f", "mp3", "pipe:1", "-loglevel", "error",
    ]
