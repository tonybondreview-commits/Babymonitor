"""Utilita' di rete: individua l'IP locale del "cervello" sulla rete di casa,
per costruire l'indirizzo da aprire sugli altri dispositivi (e il QR code).
"""

from __future__ import annotations

import socket


def get_lan_ip() -> str:
    """Ritorna l'IP locale (es. 192.168.x.x) usato per raggiungere la rete.

    Il trucco della connessione UDP non invia dati: serve solo a far scegliere
    al sistema l'interfaccia di rete giusta. Funziona senza internet.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def app_url(port: int) -> str:
    return f"http://{get_lan_ip()}:{port}"
