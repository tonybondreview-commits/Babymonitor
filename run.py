#!/usr/bin/env python3
"""Avvio del Baby Monitor.

Uso:
    python run.py                 # usa config.yaml
    python run.py --config mio.yaml

Poi apri dal telefono/iPad, sulla stessa rete WiFi:
    http://<ip-del-cervello>:8080
"""

from __future__ import annotations

import argparse
import signal
import sys

from babymonitor.config import Config
from babymonitor.controller import Controller
from babymonitor.server import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Baby Monitor per camere Fredi/Yoosee")
    parser.add_argument("--config", default="config.yaml", help="percorso del file di configurazione")
    args = parser.parse_args()

    config = Config.load(args.config)
    controller = Controller(config)
    controller.start()

    if not controller.is_configured():
        print("[baby-monitor] Prima configurazione: apri l'app e segui il wizard.")
    else:
        print(f"[baby-monitor] Camera RTSP: {_mask(config.camera.build_url())}")

    app = create_app(controller)

    def shutdown(*_):
        print("\n[baby-monitor] Arresto...")
        controller.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"[baby-monitor] Apri dal telefono/iPad:  http://<ip-di-questo-dispositivo>:{config.server.port}")
    app.run(host=config.server.host, port=config.server.port, threaded=True)
    return 0


def _mask(url: str) -> str:
    """Nasconde la password nei log."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.split("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:****@{host}"
    return url


if __name__ == "__main__":
    raise SystemExit(main())
