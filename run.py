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

from babymonitor.camera import Camera
from babymonitor.config import Config
from babymonitor.events import EventBus
from babymonitor.lullaby import LullabyLibrary
from babymonitor.monitor import Monitor
from babymonitor.server import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Baby Monitor per camere Fredi/Yoosee")
    parser.add_argument("--config", default="config.yaml", help="percorso del file di configurazione")
    args = parser.parse_args()

    config = Config.load(args.config)

    rtsp_url = config.camera.build_url()
    print(f"[baby-monitor] Camera RTSP: {_mask(rtsp_url)}")

    camera = Camera(rtsp_url)
    bus = EventBus()
    monitor = Monitor(config, camera, bus)
    library = LullabyLibrary(config.lullaby.directory)

    camera.start()
    monitor.start()

    app = create_app(config, monitor, bus, library)

    def shutdown(*_):
        print("\n[baby-monitor] Arresto...")
        monitor.stop()
        camera.stop()
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
