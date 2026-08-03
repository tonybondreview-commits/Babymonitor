"""Test del parsing della ricerca camere (senza usare la rete)."""

from babymonitor.discovery import extract_ips


def test_extract_ips_from_xaddrs():
    sample = (
        "<d:XAddrs>http://192.168.1.50/onvif/device_service "
        "https://192.168.1.51:8080/onvif/device_service</d:XAddrs>"
    )
    ips = extract_ips(sample)
    assert "192.168.1.50" in ips
    assert "192.168.1.51" in ips


def test_extract_ips_empty():
    assert extract_ips("nessun indirizzo qui") == []
