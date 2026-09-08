"""Riconoscimento del tipo di camera e suggerimenti su misura.

Ogni marca vuole le sue credenziali e i suoi percorsi RTSP:

* **Fredi / Yoosee** (e cloni): utente ``admin`` + la password del dispositivo,
  ONVIF da attivare nell'app; percorsi ``onvif1`` / ``onvif2``.
* **TP-Link Tapo** (C100, C110, C200, C210, C310...): NON accetta l'account
  TP-Link. Serve l'**Account telecamera** creato nell'app Tapo
  (Impostazioni dispositivo -> Avanzate -> Account telecamera); i percorsi sono
  ``stream1`` (alta qualita') e ``stream2`` (leggero) e la porta ONVIF e' 2020.

Riconosciamo la marca guardando quali porte "di servizio" sono aperte: e' un
controllo locale, veloce e senza credenziali, e serve solo per dare il consiglio
giusto quando qualcosa non funziona.
"""

from __future__ import annotations

import re
import socket

TAPO = "tapo"
YOOSEE = "yoosee"

# Porte tipiche di ciascuna marca (la prima che risponde vince).
BRAND_PORTS: dict[str, tuple[int, ...]] = {
    TAPO: (2020,),            # porta ONVIF delle Tapo
    YOOSEE: (8899, 5000),     # porte ONVIF/servizio delle Fredi-Yoosee
}

# Percorsi RTSP da provare per primi, per marca.
BRAND_PATHS: dict[str, tuple[str, ...]] = {
    TAPO: ("stream1", "stream2"),
    YOOSEE: ("onvif1", "onvif2"),
}

# Porta ONVIF di default, per marca (0 = cercala fra quelle comuni).
BRAND_ONVIF_PORT: dict[str, int] = {TAPO: 2020, YOOSEE: 0}

TAPO_HINT = (
    "Sembra una TP-Link Tapo: il video RTSP non usa l'account TP-Link. "
    "Apri l'app Tapo -> la tua camera -> ingranaggio in alto -> Avanzate -> "
    "\"Account telecamera\", crea li' utente e password e scrivi QUELLI qui."
)

YOOSEE_HINT = (
    "Controlla utente e password della camera e che ONVIF sia attivo "
    "nell'app Yoosee (di solito l'utente e' \"admin\")."
)

GENERIC_HINT = (
    "Controlla utente e password: molte camere vogliono credenziali dedicate "
    "allo streaming, diverse da quelle con cui entri nell'app del produttore. "
    "Se e' una TP-Link Tapo devi creare l'\"Account telecamera\" "
    "(app Tapo -> ingranaggio -> Avanzate -> Account telecamera): "
    "l'account TP-Link non funziona per il video."
)

# Il realm dell'header WWW-Authenticate dice spesso chi ha fatto la camera:
# le TP-Link rispondono con qualcosa come 'TP-LINK IP-Camera'.
_REALM_BRANDS = {TAPO: ("tp-link", "tplink", "tapo")}

_REALM_RE = re.compile(r'realm="([^"]*)"', re.IGNORECASE)


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    """True se la porta TCP risponde. Non solleva mai eccezioni."""
    if not host:
        return False
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def rtsp_auth_realm(host: str, port: int = 554, timeout: float = 1.5) -> str:
    """Chiede il video senza credenziali e legge il "realm" della richiesta di
    autenticazione (l'etichetta che la camera si da' da sola).

    Funziona anche quando utente e password sono sbagliati: e' proprio la
    risposta "401" a contenere il realm. Proviamo due indirizzi sulla stessa
    connessione, perche' alcune camere rispondono "404" (senza chiedere la
    password) se il percorso non esiste. Ritorna "" se non lo ottiene.
    """
    if not host:
        return ""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        for cseq, path in enumerate(("", "stream1"), start=1):
            request = (
                "DESCRIBE rtsp://%s:%d/%s RTSP/1.0\r\n"
                "CSeq: %d\r\n"
                "User-Agent: BabyMonitor\r\n"
                "Accept: application/sdp\r\n\r\n" % (host, port, path, cseq)
            )
            s.sendall(request.encode("ascii"))
            data = s.recv(2048).decode("utf-8", "ignore")
            m = _REALM_RE.search(data)
            if m:
                return m.group(1)
    except OSError:
        return ""
    finally:
        s.close()
    return ""


def detect_brand(host: str, timeout: float = 0.4, rtsp_port: int = 554) -> str:
    """Indovina la marca della camera ("" se non ci riesce).

    Prima chiede alla camera stessa come si chiama (realm RTSP), poi ripiega
    sulle porte di servizio aperte.
    """
    realm = rtsp_auth_realm(host, rtsp_port).lower()
    if realm:
        for brand, needles in _REALM_BRANDS.items():
            if any(n in realm for n in needles):
                return brand
    for brand, ports in BRAND_PORTS.items():
        for port in ports:
            if port_open(host, port, timeout):
                return brand
    return ""


def auth_hint(brand: str) -> str:
    """Consiglio da mostrare quando la camera rifiuta utente/password."""
    return {TAPO: TAPO_HINT, YOOSEE: YOOSEE_HINT}.get(brand, GENERIC_HINT)


def priority_paths(brand: str) -> list[str]:
    """Percorsi RTSP da provare per primi per quella marca."""
    return list(BRAND_PATHS.get(brand, ()))


def onvif_port_for(brand: str) -> int:
    """Porta ONVIF consigliata (0 = da cercare)."""
    return BRAND_ONVIF_PORT.get(brand, 0)
