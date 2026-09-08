"""Test del backend camera (ffmpeg + Pillow), senza camera reale.

Verifichiamo lo "spezzettamento" dei fotogrammi JPEG dal flusso MJPEG e la
decodifica in scala di grigi usata per il rilevamento del movimento.
"""

import io

import numpy as np
import pytest

from babymonitor import camera as cammod
from babymonitor.camera import Camera, split_jpegs, probe_rtsp
from babymonitor.camera import test_rtsp as check_rtsp
from babymonitor.config import CameraConfig
from PIL import Image


@pytest.fixture(autouse=True)
def no_brand_probe(monkeypatch):
    """Niente socket veri per riconoscere la marca: nei test la camera e' generica."""
    monkeypatch.setattr(cammod, "detect_brand", lambda host, **kw: "")


def make_jpeg(color=128, size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (color, color, color)).save(buf, format="JPEG")
    data = buf.getvalue()
    assert data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"
    return data


def test_quality_presets():
    from babymonitor.camera import quality_preset, QUALITY_PRESETS
    assert quality_preset("high")["width"] == 960
    assert quality_preset("low")["fps"] == 6
    assert quality_preset("sconosciuta") == QUALITY_PRESETS["medium"]


def test_split_two_frames():
    a, b = make_jpeg(50), make_jpeg(200)
    frames, rest = split_jpegs(a + b)
    assert len(frames) == 2
    assert rest == b""


def test_split_keeps_incomplete_tail():
    a = make_jpeg(50)
    frames, rest = split_jpegs(a + b"\xff\xd8partial-next-frame")
    assert len(frames) == 1
    assert rest.startswith(b"\xff\xd8")  # il frame incompleto resta nel buffer


def test_split_drops_leading_garbage():
    a = make_jpeg(80)
    frames, rest = split_jpegs(b"rumore-iniziale" + a)
    assert len(frames) == 1
    assert rest == b""


def test_process_produces_gray_frame():
    cam = Camera("rtsp://fake", target_width=480, motion_width=320)
    cam._process(make_jpeg(120, size=(640, 480)))
    fid, gray = cam.read_gray()
    assert fid == 1
    assert isinstance(gray, np.ndarray) and gray.ndim == 2
    assert gray.shape[1] == 320          # ridimensionato alla larghezza d'analisi
    assert cam.latest_jpeg() is not None  # JPEG disponibile per il browser


def test_test_rtsp_no_ffmpeg(monkeypatch):
    # Se ffmpeg non c'e', deve fallire con grazia (non sollevare eccezioni).
    monkeypatch.setattr("babymonitor.camera._ffmpeg_bin", lambda: "ffmpeg-inesistente-xyz")
    res = check_rtsp("rtsp://fake", timeout=3)
    assert res["ok"] is False


def test_probe_finds_working_path(monkeypatch):
    # Simula che solo /onvif2 (in TCP) risponda: la sonda deve trovarlo.
    def fake(url, timeout=6.0, transport="tcp"):
        ok = url.endswith("/onvif2")
        return {"ok": ok, "error": "" if ok else "404 Not Found"}
    monkeypatch.setattr(cammod, "test_rtsp", fake)
    cam = CameraConfig(ip="192.168.1.67", username="admin", password="x")
    res = probe_rtsp(cam, timeout_each=0.01)
    assert res["ok"] is True
    assert res["path"] == "onvif2"
    assert res["url"].endswith("192.168.1.67:554/onvif2")


def test_probe_finds_udp_only_camera(monkeypatch):
    # Camera che risponde solo in UDP con credenziali (caso Yoosee reale).
    def fake(url, timeout=6.0, transport="tcp"):
        if url.endswith("/onvif1") and "@" in url and transport == "udp":
            return {"ok": True, "error": ""}
        if transport == "tcp":
            return {"ok": False, "error": "Nonmatching transport in server reply"}
        return {"ok": False, "error": "401 Unauthorized"}
    monkeypatch.setattr(cammod, "test_rtsp", fake)
    cam = CameraConfig(ip="192.168.1.67", username="admin", password="admin123")
    res = probe_rtsp(cam, timeout_each=0.01)
    assert res["ok"] is True
    assert res["path"] == "onvif1"
    assert res["transport"] == "udp"


def test_probe_stops_when_unreachable(monkeypatch):
    calls = []
    def fake(url, timeout=6.0, transport="tcp"):
        calls.append(url)
        return {"ok": False, "error": "No route to host"}
    monkeypatch.setattr(cammod, "test_rtsp", fake)
    cam = CameraConfig(ip="10.0.0.9", username="admin", password="x")
    res = probe_rtsp(cam, timeout_each=0.01)
    assert res["ok"] is False
    assert len(calls) == 1  # non prova tutto se l'IP e' irraggiungibile


def test_probe_falls_back_without_credentials(monkeypatch):
    # Camera che rifiuta le credenziali (401) ma funziona senza.
    def fake(url, timeout=6.0, transport="tcp"):
        if "@" in url:
            return {"ok": False, "error": "401 Unauthorized"}
        return {"ok": url.endswith("/onvif1"), "error": ""}
    monkeypatch.setattr(cammod, "test_rtsp", fake)
    cam = CameraConfig(ip="192.168.1.67", username="admin", password="x")
    res = probe_rtsp(cam, timeout_each=0.01)
    assert res["ok"] is True
    assert "@" not in res["url"]        # variante senza credenziali
    assert res["path"] == "onvif1"


def test_probe_both_auth_fail(monkeypatch):
    # Sempre 401: credenziali rifiutate.
    def fake(url, timeout=6.0, transport="tcp"):
        return {"ok": False, "error": "401 Unauthorized"}
    monkeypatch.setattr(cammod, "test_rtsp", fake)
    cam = CameraConfig(ip="192.168.1.67", username="admin", password="x")
    res = probe_rtsp(cam, timeout_each=0.01)
    assert res["ok"] is False
    assert "rifiutat" in res["error"].lower()


def test_probe_uses_explicit_url(monkeypatch):
    def fake(url, timeout=6.0, transport="tcp"):
        return {"ok": True, "error": ""}
    monkeypatch.setattr(cammod, "test_rtsp", fake)
    cam = CameraConfig(rtsp_url="rtsp://admin:x@1.2.3.4:554/custom")
    res = probe_rtsp(cam)
    assert res["ok"] is True
    assert res["url"] == "rtsp://admin:x@1.2.3.4:554/custom"


def test_ordered_paths_puts_brand_first():
    # Su una Tapo i suoi percorsi vanno provati per primi, senza duplicati.
    paths = cammod.ordered_paths("tapo")
    assert paths[:2] == ["stream1", "stream2"]
    assert paths.count("stream1") == 1
    assert set(cammod.CANDIDATE_PATHS).issubset(set(paths))
    # Marca sconosciuta: ordine originale.
    assert cammod.ordered_paths("") == cammod.CANDIDATE_PATHS


def test_probe_gives_up_quickly_on_wrong_password(monkeypatch):
    # Camera che risponde sempre 401: inutile provare tutti i percorsi.
    calls = []

    def fake(url, timeout=6.0, transport="tcp"):
        calls.append(url)
        return {"ok": False, "error": "401 Unauthorized"}

    monkeypatch.setattr(cammod, "test_rtsp", fake)
    cam = CameraConfig(ip="192.168.1.50", username="admin", password="sbagliata")
    res = probe_rtsp(cam, timeout_each=0.01, brand="tapo")
    assert res["ok"] is False
    assert "rifiutat" in res["error"].lower()
    # 3 percorsi x 2 trasporti x 2 varianti di credenziali, poi si ferma.
    assert len(calls) == cammod.AUTH_GIVE_UP_AFTER * 4
    assert "Account telecamera" in res["hint"]   # consiglio su misura per Tapo


def test_probe_hint_only_when_credentials_are_the_problem(monkeypatch):
    def fake(url, timeout=6.0, transport="tcp"):
        return {"ok": False, "error": "404 Not Found"}

    monkeypatch.setattr(cammod, "test_rtsp", fake)
    cam = CameraConfig(ip="192.168.1.50", username="admin", password="x")
    res = probe_rtsp(cam, timeout_each=0.01, brand="tapo")
    assert res["ok"] is False
    assert res["hint"] == ""


def test_probe_finds_tapo_stream(monkeypatch):
    # Con le credenziali giuste la Tapo risponde su /stream1.
    def fake(url, timeout=6.0, transport="tcp"):
        ok = url.endswith("/stream1") and "@" in url
        return {"ok": ok, "error": "" if ok else "404 Not Found"}

    monkeypatch.setattr(cammod, "test_rtsp", fake)
    cam = CameraConfig(ip="192.168.1.50", username="baby", password="segreta")
    res = probe_rtsp(cam, timeout_each=0.01, brand="tapo")
    assert res["ok"] is True
    assert res["path"] == "stream1"
    assert res["brand"] == "tapo"
