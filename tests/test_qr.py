"""Test della generazione QR e dell'individuazione dell'IP locale."""

import pytest

from babymonitor import qr as qrgen
from babymonitor.netinfo import get_lan_ip, app_url


@pytest.mark.skipif(not qrgen.HAS_QR, reason="modulo qrcode non installato")
def test_svg_contains_rects():
    out = qrgen.svg("http://192.168.1.50:8080")
    assert out.startswith("<svg")
    assert "<rect" in out
    assert out.rstrip().endswith("</svg>")


@pytest.mark.skipif(not qrgen.HAS_QR, reason="modulo qrcode non installato")
def test_ascii_non_empty():
    out = qrgen.ascii_qr("http://192.168.1.50:8080")
    assert out and "\n" in out


def test_lan_ip_is_string():
    ip = get_lan_ip()
    assert isinstance(ip, str) and ip.count(".") == 3


def test_app_url_format():
    url = app_url(8080)
    assert url.startswith("http://") and url.endswith(":8080")
