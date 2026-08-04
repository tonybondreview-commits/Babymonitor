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


_ENCODER: str | None = None


def _has_encoder(name: str) -> bool:
    try:
        p = subprocess.run([_ffmpeg(), "-hide_banner", "-encoders"],
                           capture_output=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return name.encode() in (p.stdout or b"")


def pick_encoder() -> str:
    """Sceglie 'mp3' se ffmpeg ha libmp3lame, altrimenti 'aac' (sempre presente)."""
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = "mp3" if _has_encoder("libmp3lame") else "aac"
    return _ENCODER


def audio_mime() -> str:
    return "audio/mpeg" if pick_encoder() == "mp3" else "audio/aac"


def audio_command(url: str, transport: str = "tcp") -> list[str]:
    """Comando ffmpeg: RTSP -> audio in streaming continuo (solo audio)."""
    if pick_encoder() == "mp3":
        # write_xing 0 + niente id3: header adatti a uno stream "dal vivo"
        # (senza durata) che Safari riproduce subito.
        codec = ["-c:a", "libmp3lame", "-b:a", "48k",
                 "-write_xing", "0", "-id3v2_version", "0", "-f", "mp3"]
    else:
        codec = ["-c:a", "aac", "-b:a", "64k", "-f", "adts"]
    return [
        _ffmpeg(), "-nostdin", "-rtsp_transport", transport,
        "-fflags", "nobuffer", "-i", url,
        "-vn", "-ac", "1", "-flush_packets", "1", *codec, "pipe:1", "-loglevel", "error",
    ]
