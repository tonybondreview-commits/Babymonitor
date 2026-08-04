"""Test del modulo audio (senza camera/ffmpeg reali)."""

from babymonitor import audio as a
from babymonitor.audio import audio_command


def test_audio_command_mp3(monkeypatch):
    monkeypatch.setattr(a, "pick_encoder", lambda: "mp3")
    cmd = audio_command("rtsp://x/y", "udp")
    assert "-vn" in cmd
    assert "-rtsp_transport" in cmd and "udp" in cmd
    assert "libmp3lame" in cmd
    assert cmd[-3:] == ["pipe:1", "-loglevel", "error"]


def test_audio_command_aac_fallback(monkeypatch):
    monkeypatch.setattr(a, "pick_encoder", lambda: "aac")
    cmd = audio_command("rtsp://x/y", "tcp")
    assert "-vn" in cmd
    assert "aac" in cmd and "adts" in cmd
    assert cmd[-3:] == ["pipe:1", "-loglevel", "error"]


def test_pick_encoder_falls_back_to_aac(monkeypatch):
    a._ENCODER = None
    monkeypatch.setattr(a, "_has_encoder", lambda name: False)
    assert a.pick_encoder() == "aac"
    a._ENCODER = None


def test_has_audio_no_ffprobe(monkeypatch):
    monkeypatch.setattr(a, "_ffprobe", lambda: "ffprobe-inesistente-xyz")
    assert a.has_audio("rtsp://x/y", "tcp", timeout=3) is False
