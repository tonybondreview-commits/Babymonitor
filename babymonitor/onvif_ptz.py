"""Controllo PTZ (movimento camera) via ONVIF.

Implementazione minimale in sola libreria standard (niente dipendenze extra,
cosi' gira anche su Termux): costruisce le richieste SOAP con autenticazione
WS-Security (UsernameToken + PasswordDigest) e le invia alla camera.

Molte camere economiche hanno endpoint/porta ONVIF diversi: qui proviamo le
combinazioni piu' comuni e memorizziamo quella che funziona.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

# Porte ONVIF piu' comuni (la Fredi dell'utente usa la 5000).
# 5000/8899 = Fredi-Yoosee, 2020 = TP-Link Tapo, le altre sono comuni
# su molte camere ONVIF economiche.
COMMON_ONVIF_PORTS = [5000, 2020, 80, 8080, 8899, 8000, 2000]
# Percorsi possibili dei servizi ONVIF.
DEVICE_PATHS = ["/onvif/device_service"]
MEDIA_PATHS = ["/onvif/media_service", "/onvif/Media", "/onvif/media", "/onvif/device_service"]
PTZ_PATHS = ["/onvif/ptz_service", "/onvif/PTZ", "/onvif/ptz", "/onvif/device_service"]

_NS_DEV = "http://www.onvif.org/ver10/device/wsdl"
_NS_MEDIA = "http://www.onvif.org/ver10/media/wsdl"
_NS_PTZ = "http://www.onvif.org/ver20/ptz/wsdl"
_NS_SCHEMA = "http://www.onvif.org/ver10/schema"

_ENV12 = ('<?xml version="1.0" encoding="UTF-8"?>'
          '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">{header}<s:Body>{body}</s:Body></s:Envelope>')
_ENV11 = ('<?xml version="1.0" encoding="UTF-8"?>'
          '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">{header}<s:Body>{body}</s:Body></s:Envelope>')

# Opener che NON usa proxy (le richieste vanno alla camera in rete locale).
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _security(user: str, password: str) -> str:
    if not user:
        return ""
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = os.urandom(16)
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    n64 = base64.b64encode(nonce).decode()
    return (
        '<s:Header><Security s:mustUnderstand="1" '
        'xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
        '<UsernameToken><Username>{u}</Username>'
        '<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{d}</Password>'
        '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{n}</Nonce>'
        '<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{c}</Created>'
        '</UsernameToken></Security></s:Header>'
    ).format(u=user, d=digest, n=n64, c=created)


def _http(url: str, envelope: str, headers: dict, timeout: float) -> str:
    req = urllib.request.Request(url, data=envelope.encode("utf-8"), headers=headers, method="POST")
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:  # i "fault" SOAP arrivano come 400/500 con corpo
        try:
            return e.read().decode("utf-8", "ignore")
        except Exception:
            return ""
    except Exception:
        return ""


def _looks_ok(resp: str) -> bool:
    if not resp:
        return False
    low = resp.lower()
    return not any(k in low for k in ("fault", "versionmismatch", "actionnotsupported"))


# Formato SOAP che ha funzionato ("12" o "11"): una volta scoperto, si usa
# solo quello, cosi' ogni comando e' una sola richiesta (niente tentativi a vuoto).
_PREFERRED_SOAP: str | None = None


def _send(url: str, header: str, body: str, ver: str, action: str, timeout: float) -> str:
    if ver == "12":
        ct = "application/soap+xml; charset=utf-8"
        if action:
            ct += '; action="%s"' % action
        return _http(url, _ENV12.format(header=header, body=body), {"Content-Type": ct}, timeout)
    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '"%s"' % action}
    return _http(url, _ENV11.format(header=header, body=body), headers, timeout)


def _post(url: str, body: str, user: str, password: str, action: str = "", timeout: float = 6.0) -> str:
    """Invia una richiesta SOAP. Ricorda il formato (1.2/1.1) che funziona."""
    global _PREFERRED_SOAP
    header = _security(user, password)
    order = ["12", "11"] if _PREFERRED_SOAP != "11" else ["11", "12"]
    last = ""
    for ver in order:
        resp = _send(url, header, body, ver, action, timeout)
        last = resp
        if _looks_ok(resp):
            _PREFERRED_SOAP = ver
            return resp
    return last


# ---- corpi SOAP -----------------------------------------------------------
def _b_getdatetime() -> str:
    return '<GetSystemDateAndTime xmlns="%s"/>' % _NS_DEV


def _b_getprofiles() -> str:
    return '<GetProfiles xmlns="%s"/>' % _NS_MEDIA


def _b_move(token: str, x: float, y: float, z: float) -> str:
    return (
        '<ContinuousMove xmlns="%s"><ProfileToken>%s</ProfileToken>'
        '<Velocity><PanTilt x="%.2f" y="%.2f" xmlns="%s"/><Zoom x="%.2f" xmlns="%s"/></Velocity>'
        '</ContinuousMove>' % (_NS_PTZ, token, x, y, _NS_SCHEMA, z, _NS_SCHEMA)
    )


def _b_stop(token: str) -> str:
    return ('<Stop xmlns="%s"><ProfileToken>%s</ProfileToken>'
            '<PanTilt>true</PanTilt><Zoom>true</Zoom></Stop>' % (_NS_PTZ, token))


def find_onvif_port(ip: str, ports=None, timeout: float = 2.0) -> int:
    """Trova la porta ONVIF provando GetSystemDateAndTime (non serve auth)."""
    for port in (ports or COMMON_ONVIF_PORTS):
        url = "http://%s:%d%s" % (ip, port, DEVICE_PATHS[0])
        resp = _post(url, _b_getdatetime(), "", "", action=_NS_DEV + "/GetSystemDateAndTime", timeout=timeout)
        if "SystemDateAndTime" in resp or "UTCDateTime" in resp or "LocalDateTime" in resp:
            return port
    return 0


def parse_profile(resp: str) -> tuple[str, bool]:
    """Dal GetProfilesResponse estrae (token_primo_profilo, ha_PTZ)."""
    m = re.search(r'token="([^"]+)"', resp)
    token = m.group(1) if m else ""
    has_ptz = "PTZConfiguration" in resp
    return token, has_ptz


def get_capabilities(base_url: str, user: str, password: str) -> tuple[str, str, bool]:
    """Chiede la 'mappa dei servizi' ONVIF. Ritorna (media_XAddr, ptz_XAddr,
    ha_risposto). Molte camere tengono Media e PTZ su indirizzi separati."""
    body = ('<GetCapabilities xmlns="%s"><Category>All</Category></GetCapabilities>' % _NS_DEV)
    resp = _post(base_url + "/onvif/device_service", body, user, password,
                 action=_NS_DEV + "/GetCapabilities")
    xaddrs = re.findall(r"XAddr>\s*(https?://[^<\s]+)", resp)
    media = next((x for x in xaddrs if "media" in x.lower()), "")
    ptz = next((x for x in xaddrs if "ptz" in x.lower()), "")
    responded = "Envelope" in resp or "XAddr" in resp
    return media, ptz, responded


class PtzController:
    """Controlla il PTZ di una camera ONVIF. Si auto-configura al primo uso."""

    DIRS = {
        "left": (-0.6, 0.0, 0.0), "right": (0.6, 0.0, 0.0),
        "up": (0.0, 0.6, 0.0), "down": (0.0, -0.6, 0.0),
        "zoomin": (0.0, 0.0, 0.6), "zoomout": (0.0, 0.0, -0.6),
    }

    def __init__(self, ip: str, username: str, password: str, onvif_port: int = 0):
        self.ip = ip
        self.user = username
        self.password = password
        self.port = onvif_port or 0
        self.token = ""
        self.ptz_url = ""
        self.available = False
        self._checked = False
        self._lock = threading.Lock()

    def _base(self) -> str:
        return "http://%s:%d" % (self.ip, self.port)

    def _ensure(self) -> bool:
        with self._lock:
            if self._checked:
                return self.available
            self._checked = True
            if not self.ip:
                return False

            ports = [self.port] if self.port else COMMON_ONVIF_PORTS
            for port in ports:
                base = "http://%s:%d" % (self.ip, port)
                media_x, ptz_x, responded = get_capabilities(base, self.user, self.password)
                if not responded:
                    continue  # non e' la porta ONVIF
                self.port = port

                # GetProfiles: prima sull'indirizzo Media dato dalla camera,
                # poi sui percorsi comuni come riserva.
                token, has_ptz = "", False
                media_urls = ([media_x] if media_x else []) + [base + p for p in MEDIA_PATHS]
                for murl in media_urls:
                    resp = _post(murl, _b_getprofiles(), self.user, self.password,
                                 action=_NS_MEDIA + "/GetProfiles")
                    token, has_ptz = parse_profile(resp)
                    if token:
                        break
                if not token:
                    continue
                self.token = token

                # Endpoint PTZ: prima quello dato dalla camera, poi i comuni.
                ptz_urls = ([ptz_x] if ptz_x else []) + [base + p for p in PTZ_PATHS]
                for purl in ptz_urls:
                    resp = _post(purl, _b_stop(token), self.user, self.password, action=_NS_PTZ + "/Stop")
                    if "StopResponse" in resp:
                        self.ptz_url = purl
                        self.available = True
                        break
                if not self.available and (ptz_x or has_ptz):
                    self.ptz_url = ptz_x or (base + PTZ_PATHS[0])
                    self.available = True
                return self.available
            return False

    def is_available(self) -> bool:
        return self._ensure()

    def diagnose(self) -> dict:
        """Ripercorre passo-passo il rilevamento ONVIF/PTZ e racconta cosa
        succede a ogni tappa. Serve per capire PERCHE' il joystick non compare
        (porta sbagliata, credenziali rifiutate, camera senza PTZ...).

        NON mette in cache e NON espone la password.
        """
        steps: list[dict] = []
        out = {
            "ip": self.ip,
            "username": self.user,
            "has_password": bool(self.password),
            "configured_port": self.port,
            "available": False,
            "ptz_url": "",
            "steps": steps,
            "hint": "",
        }
        if not self.ip:
            out["hint"] = "IP della camera non impostato."
            return out

        ports = [self.port] if self.port else COMMON_ONVIF_PORTS
        onvif_ok = False
        for port in ports:
            base = "http://%s:%d" % (self.ip, port)
            media_x, ptz_x, responded = get_capabilities(base, self.user, self.password)
            steps.append({"port": port, "onvif_responded": responded,
                          "media_xaddr": media_x, "ptz_xaddr": ptz_x})
            if not responded:
                continue
            onvif_ok = True

            token, has_ptz = "", False
            media_urls = ([media_x] if media_x else []) + [base + p for p in MEDIA_PATHS]
            for murl in media_urls:
                resp = _post(murl, _b_getprofiles(), self.user, self.password,
                             action=_NS_MEDIA + "/GetProfiles")
                token, has_ptz = parse_profile(resp)
                if token or "fault" in resp.lower():
                    steps.append({"port": port, "get_profiles_url": murl,
                                  "token_found": bool(token), "has_ptz_config": has_ptz,
                                  "auth_fault": "fault" in resp.lower()})
                if token:
                    break
            if not token:
                out["hint"] = ("La camera parla ONVIF sulla porta %d ma non da' i "
                               "profili video: quasi sempre utente/password ONVIF "
                               "sbagliati (sulla Tapo: Account telecamera)." % port)
                continue

            ptz_urls = ([ptz_x] if ptz_x else []) + [base + p for p in PTZ_PATHS]
            for purl in ptz_urls:
                resp = _post(purl, _b_stop(token), self.user, self.password,
                             action=_NS_PTZ + "/Stop")
                ok = "StopResponse" in resp
                steps.append({"port": port, "ptz_stop_url": purl, "stop_ok": ok})
                if ok:
                    out["available"] = True
                    out["ptz_url"] = purl
                    out["configured_port"] = port
                    return out
            if ptz_x or has_ptz:
                out["available"] = True
                out["ptz_url"] = ptz_x or (base + PTZ_PATHS[0])
                out["configured_port"] = port
                out["hint"] = ("PTZ dichiarato dalla camera ma il comando Stop non "
                               "ha risposto: probabile endpoint PTZ diverso.")
                return out
            out["hint"] = ("La camera ha i profili ma NON dichiara il PTZ: questo "
                           "modello potrebbe non essere motorizzato, o il PTZ e' su "
                           "un endpoint non standard.")

        if not onvif_ok:
            out["hint"] = ("Nessuna risposta ONVIF su %s. Sulla Tapo la porta ONVIF "
                           "e' la 2020: controlla che sia raggiungibile e che le "
                           "credenziali siano quelle dell'Account telecamera."
                           % ", ".join(str(p) for p in ports))
        return out

    def move(self, direction: str) -> bool:
        if direction == "stop":
            return self.stop()
        if direction not in self.DIRS or not self._ensure():
            return False
        x, y, z = self.DIRS[direction]
        resp = _post(self.ptz_url, _b_move(self.token, x, y, z), self.user, self.password,
                     action=_NS_PTZ + "/ContinuousMove", timeout=3.0)
        return "ContinuousMoveResponse" in resp or "Envelope" in resp

    def stop(self) -> bool:
        if not self._ensure():
            return False
        resp = _post(self.ptz_url, _b_stop(self.token), self.user, self.password,
                     action=_NS_PTZ + "/Stop", timeout=3.0)
        return "StopResponse" in resp or "Envelope" in resp
