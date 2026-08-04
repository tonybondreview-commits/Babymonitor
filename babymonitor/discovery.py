"""Ricerca automatica delle camere sulla rete locale (ONVIF WS-Discovery).

Invia un messaggio multicast a cui le camere ONVIF (come le Fredi/Yoosee con
ONVIF attivo) rispondono, e raccoglie i loro indirizzi IP. Cosi' il wizard
puo' proporre la camera senza far cercare l'IP a mano.

Non richiede internet: tutto avviene sulla rete di casa.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import re
import socket
import time
import uuid

from .netinfo import get_lan_ip

WSD_ADDR = "239.255.255.250"
WSD_PORT = 3702

_PROBE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"'
    ' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"'
    ' xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    '<e:Header>'
    '<w:MessageID>uuid:{mid}</w:MessageID>'
    '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
    '<w:Action e:mustUnderstand="true">'
    'http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
    '</e:Header>'
    '<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>'
    '</e:Envelope>'
)

_IP_RE = re.compile(r"https?://(\d{1,3}(?:\.\d{1,3}){3})")


def discover_cameras(timeout: float = 3.0) -> list[str]:
    """Ritorna la lista di IP delle camere ONVIF trovate sulla rete."""
    message = _PROBE.format(mid=uuid.uuid4()).encode("utf-8")
    found: dict[str, None] = {}

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.6)
    except OSError:
        return []

    try:
        sock.sendto(message, (WSD_ADDR, WSD_PORT))
    except OSError:
        sock.close()
        return []

    end = time.time() + timeout
    while time.time() < end:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        text = data.decode("utf-8", errors="ignore")
        # IP dentro gli XAddrs della risposta ONVIF...
        for ip in _IP_RE.findall(text):
            found.setdefault(ip, None)
        # ...e comunque l'IP che ci ha risposto.
        found.setdefault(addr[0], None)

    sock.close()
    return sorted(found.keys(), key=lambda s: tuple(int(x) for x in s.split(".")))


def extract_ips(text: str) -> list[str]:
    """Estrae gli IP dagli XAddrs (esposta per i test)."""
    return _IP_RE.findall(text)


def _sort_ips(ips) -> list[str]:
    def key(s):
        try:
            return tuple(int(x) for x in s.split("."))
        except ValueError:
            return (999,)
    return sorted(set(ips), key=key)


def scan_subnet(port: int = 554, timeout: float = 0.5, max_workers: int = 100) -> list[str]:
    """Cerca sulla rete locale gli host con la porta RTSP (554) aperta.

    Non usa il multicast (che Android blocca): prova un collegamento diretto a
    ogni indirizzo della sottorete /24. Piu' lento del WS-Discovery ma molto
    piu' affidabile per trovare la camera.
    """
    ip = get_lan_ip()
    try:
        net = ipaddress.ip_network(ip + "/24", strict=False)
    except ValueError:
        return []

    def check(host: str) -> str | None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            rc = s.connect_ex((host, port))
        except OSError:
            rc = 1
        finally:
            s.close()
        return host if rc == 0 else None

    hosts = [str(h) for h in net.hosts()]
    found: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for res in ex.map(check, hosts):
            if res:
                found.append(res)
    return _sort_ips(found)


def find_cameras() -> list[str]:
    """Trova le camere: prima via ONVIF (veloce), poi via scansione porta RTSP."""
    cams = discover_cameras()
    extra = scan_subnet(554)
    return _sort_ips(list(cams) + list(extra))
