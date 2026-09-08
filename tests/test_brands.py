"""Riconoscimento della marca della camera (senza toccare la rete vera)."""

from babymonitor import brands


def test_detect_tapo_from_realm(monkeypatch):
    # La camera si presenta da sola nella richiesta di autenticazione RTSP:
    # funziona anche quando utente/password sono sbagliati.
    monkeypatch.setattr(brands, "rtsp_auth_realm",
                        lambda host, port=554, timeout=1.5: "TP-LINK IP-Camera")
    monkeypatch.setattr(brands, "port_open", lambda *a, **k: False)
    assert brands.detect_brand("192.168.1.50") == brands.TAPO


def test_detect_tapo_from_port(monkeypatch):
    # Nessun realm utile: ripiega sulla 2020 (porta ONVIF delle Tapo).
    monkeypatch.setattr(brands, "rtsp_auth_realm",
                        lambda host, port=554, timeout=1.5: "")
    monkeypatch.setattr(brands, "port_open",
                        lambda host, port, timeout=0.4: port == 2020)
    assert brands.detect_brand("192.168.1.50") == brands.TAPO


def test_detect_yoosee(monkeypatch):
    monkeypatch.setattr(brands, "rtsp_auth_realm",
                        lambda host, port=554, timeout=1.5: "camera")
    monkeypatch.setattr(brands, "port_open",
                        lambda host, port, timeout=0.4: port in (8899, 5000))
    assert brands.detect_brand("192.168.1.67") == brands.YOOSEE


def test_detect_unknown(monkeypatch):
    monkeypatch.setattr(brands, "rtsp_auth_realm",
                        lambda host, port=554, timeout=1.5: "")
    monkeypatch.setattr(brands, "port_open", lambda host, port, timeout=0.4: False)
    assert brands.detect_brand("192.168.1.9") == ""


def test_port_open_is_safe_without_host():
    # Nessuna eccezione se l'IP non c'e' ancora (wizard appena aperto).
    assert brands.port_open("", 554) is False
    assert brands.rtsp_auth_realm("") == ""


def test_hints_and_paths():
    assert "Account telecamera" in brands.auth_hint(brands.TAPO)
    # Anche il consiglio generico cita le Tapo: la marca non sempre si riconosce.
    assert "Account telecamera" in brands.GENERIC_HINT
    assert "Yoosee" in brands.auth_hint(brands.YOOSEE)
    assert brands.auth_hint("") == brands.GENERIC_HINT
    assert brands.priority_paths(brands.TAPO) == ["stream1", "stream2"]
    assert brands.priority_paths("") == []
    assert brands.onvif_port_for(brands.TAPO) == 2020
