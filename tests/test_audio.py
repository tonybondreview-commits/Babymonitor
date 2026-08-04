"""Test del modulo audio (senza camera/ffmpeg reali)."""

from babymonitor import audio as a
from babymonitor.audio import audio_command


def test_audio_command_is_audio_only_mp3():
    cmd = audio_command("rtsp://x/y", "udp")
    assert "-vn" in cmd                       # niente video
    assert "-rtsp_transport" in cmd and "udp" in cmd
    assert cmd[-4:] == ["mp3", "pipe:1", "-loglevel", "error"]
    assert "libmp3lame" in cmd


def test_has_audio_no_ffprobe(monkeypatch):
    # Se ffprobe non c'e', deve rispondere False senza esplodere.
    monkeypatch.setattr(a, "_ffprobe", lambda: "ffprobe-inesistente-xyz")
    assert a.has_audio("rtsp://x/y", "tcp", timeout=3) is False
