"""Test del controllo PTZ ONVIF (senza camera reale, richieste simulate)."""

import base64

from babymonitor import onvif_ptz as o
from babymonitor.onvif_ptz import PtzController, parse_profile, _security


def test_parse_profile():
    resp = '<Profiles token="IPCProfilesToken0"><PTZConfiguration token="P"/></Profiles>'
    token, has_ptz = parse_profile(resp)
    assert token == "IPCProfilesToken0"
    assert has_ptz is True


def test_parse_profile_no_ptz():
    token, has_ptz = parse_profile('<Profiles token="T0"></Profiles>')
    assert token == "T0" and has_ptz is False


def test_security_has_digest_and_nonce():
    sec = _security("admin", "admin123")
    assert "<Username>admin</Username>" in sec
    assert "PasswordDigest" in sec and "Nonce" in sec and "Created" in sec


def _fake_camera(monkeypatch):
    def fake_post(url, body, user, password, action="", timeout=6.0):
        if "GetCapabilities" in body:
            return ('<s:Envelope><Media><XAddr>http://192.168.1.67:5000/onvif/Media</XAddr></Media>'
                    '<PTZ><XAddr>http://192.168.1.67:5000/onvif/PTZ</XAddr></PTZ></s:Envelope>')
        if "GetProfiles" in body:
            return ('<GetProfilesResponse><Profiles token="IPCProfilesToken0">'
                    '<PTZConfiguration token="PTZ"/></Profiles></GetProfilesResponse>')
        if "<Stop" in body:
            return "<StopResponse/>"
        if "ContinuousMove" in body:
            return "<ContinuousMoveResponse/>"
        return ""
    monkeypatch.setattr(o, "_post", fake_post)


def test_ptz_available_and_move(monkeypatch):
    _fake_camera(monkeypatch)
    ptz = PtzController("192.168.1.67", "admin", "admin123", onvif_port=5000)
    assert ptz.is_available() is True
    assert ptz.token == "IPCProfilesToken0"
    assert ptz.move("left") is True
    assert ptz.move("zoomin") is True
    assert ptz.stop() is True


def test_ptz_unavailable_without_ptz_config(monkeypatch):
    def fake_post(url, body, user, password, action="", timeout=6.0):
        if "GetCapabilities" in body:  # nessun servizio PTZ nella mappa
            return '<s:Envelope><Media><XAddr>http://192.168.1.67:5000/onvif/Media</XAddr></Media></s:Envelope>'
        if "GetProfiles" in body:
            return '<GetProfilesResponse><Profiles token="T0"></Profiles></GetProfilesResponse>'
        return ""
    monkeypatch.setattr(o, "_post", fake_post)
    ptz = PtzController("192.168.1.67", "admin", "admin123", onvif_port=5000)
    assert ptz.is_available() is False
    assert ptz.move("left") is False


def test_ptz_bad_direction(monkeypatch):
    _fake_camera(monkeypatch)
    ptz = PtzController("192.168.1.67", "admin", "admin123", onvif_port=5000)
    assert ptz.move("diagonal") is False
