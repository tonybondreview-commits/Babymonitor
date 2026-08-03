"""Test della configurazione: costruzione URL, salvataggio e ricarica."""

import os

from babymonitor.config import Config, CameraConfig


def test_build_url_from_fields():
    c = CameraConfig(ip="192.168.1.50", username="admin", password="p@ss", stream="sub")
    url = c.build_url()
    assert url == "rtsp://admin:p%40ss@192.168.1.50:554/onvif2"


def test_build_url_prefers_explicit():
    c = CameraConfig(rtsp_url="rtsp://x/y")
    assert c.build_url() == "rtsp://x/y"


def test_save_and_reload(tmp_path):
    path = os.path.join(tmp_path, "config.yaml")
    cfg = Config()
    cfg.camera.ip = "192.168.1.77"
    cfg.camera.username = "mario"
    cfg.camera.password = "segreta"
    cfg.motion.sensitivity = 80
    cfg.configured = True
    cfg.save(path)

    assert os.path.exists(path)
    reloaded = Config.load(path)
    assert reloaded.camera.ip == "192.168.1.77"
    assert reloaded.camera.username == "mario"
    assert reloaded.motion.sensitivity == 80
    assert reloaded.configured is True


def test_env_password_override(monkeypatch, tmp_path):
    path = os.path.join(tmp_path, "config.yaml")
    Config().save(path)
    monkeypatch.setenv("CAMERA_PASSWORD", "da-env")
    cfg = Config.load(path)
    assert cfg.camera.password == "da-env"
