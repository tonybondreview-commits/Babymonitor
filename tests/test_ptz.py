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


def test_candidate_ports_falls_back_beyond_saved():
    # Con una porta salvata (es. vecchia Yoosee 5000) proviamo QUELLA per prima
    # ma poi anche le altre comuni, 2020 (Tapo) inclusa.
    ptz = PtzController("192.168.1.118", "admin123", "x", onvif_port=5000)
    ports = ptz._candidate_ports()
    assert ports[0] == 5000
    assert 2020 in ports
    assert len(ports) == len(set(ports))  # nessun doppione


def test_diagnose_tries_2020_when_saved_port_dead(monkeypatch):
    # 5000 (salvata) non risponde, la Tapo risponde su 2020 con PTZ.
    def fake_post(url, body, user, password, action="", timeout=6.0):
        if ":2020" not in url:
            return ""  # solo la 2020 e' viva
        if "GetCapabilities" in body:
            return ('<s:Envelope><Media><XAddr>http://192.168.1.118:2020/onvif/Media</XAddr></Media>'
                    '<PTZ><XAddr>http://192.168.1.118:2020/onvif/PTZ</XAddr></PTZ></s:Envelope>')
        if "GetProfiles" in body:
            return ('<GetProfilesResponse><Profiles token="profile_1">'
                    '<PTZConfiguration token="PTZ"/></Profiles></GetProfilesResponse>')
        if "<Stop" in body:
            return "<StopResponse/>"
        return ""
    monkeypatch.setattr(o, "_post", fake_post)
    ptz = PtzController("192.168.1.118", "admin123", "x", onvif_port=5000)
    diag = ptz.diagnose()
    assert diag["available"] is True
    assert diag["configured_port"] == 2020
    assert ":2020" in diag["ptz_url"]
    # e il controllo "vero" trova anche lui la 2020
    assert ptz.is_available() is True


def test_default_not_treated_as_fault():
    # Un profilo che si chiama "...default..." NON deve sembrare un SOAP fault.
    ok_resp = '<GetProfilesResponse><Profiles token="profile_default_1"/></GetProfilesResponse>'
    assert o._is_soap_fault(ok_resp) is False
    assert o._looks_ok(ok_resp) is True
    # Un vero fault SI'.
    assert o._is_soap_fault('<s:Fault><s:Code/></s:Fault>') is True
    assert o._is_soap_fault('<SOAP-ENV:Fault></SOAP-ENV:Fault>') is True


def test_test_move(monkeypatch):
    _fake_camera(monkeypatch)
    ptz = PtzController("192.168.1.118", "admin123", "x", onvif_port=2020)
    res = ptz.test_move("left", seconds=0.1)
    assert res["ok"] is True and res["move_accepted"] is True
    assert res["stop_accepted"] is True
    bad = ptz.test_move("diagonale")
    assert bad["ok"] is False
