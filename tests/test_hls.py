"""Test dell'audio HLS (senza ffmpeg reale)."""

from babymonitor.hls_audio import HlsAudio


def _h():
    return HlsAudio(lambda: "rtsp://admin:x@1.2.3.4:554/onvif1", lambda: "udp")


def test_cmd_is_audio_only_hls():
    cmd = _h()._cmd()
    assert "-vn" in cmd
    assert "hls" in cmd
    assert "audio.m3u8" in cmd
    assert "udp" in cmd


def test_file_rejects_non_hls_and_traversal():
    h = _h()
    assert h.file("../config.py") is None
    assert h.file("evil.exe") is None
    # un .ts inesistente -> None (non presente su disco)
    assert h.file("seg_0.ts") is None
