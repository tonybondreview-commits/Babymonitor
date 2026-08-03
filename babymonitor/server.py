"""Server web: espone la webapp (PWA), lo stream video MJPEG, gli eventi in
tempo reale (Server-Sent Events) e le ninna nanne.

Tutto viaggia sulla rete locale: nessun dato esce da casa, nessun cloud.
"""

from __future__ import annotations

import os
import time

from flask import (
    Flask,
    Response,
    jsonify,
    request,
    send_file,
    send_from_directory,
)

from .config import Config
from .events import EventBus
from .lullaby import LullabyLibrary
from .monitor import Monitor

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def create_app(config: Config, monitor: Monitor, bus: EventBus, library: LullabyLibrary) -> Flask:
    app = Flask(__name__, static_folder=None)
    camera = monitor.camera

    # ---- PWA (file statici) -------------------------------------------
    @app.route("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.route("/<path:filename>")
    def static_files(filename):
        return send_from_directory(WEB_DIR, filename)

    # ---- video live (MJPEG) -------------------------------------------
    @app.route("/stream.mjpg")
    def stream():
        boundary = "frame"

        def generate():
            last_id = -1
            while True:
                last_id = camera.wait_for_frame(last_id, timeout=2.0)
                jpeg = camera.latest_jpeg()
                if jpeg is None:
                    time.sleep(0.1)
                    continue
                yield (
                    b"--" + boundary.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg + b"\r\n"
                )

        return Response(
            generate(),
            mimetype=f"multipart/x-mixed-replace; boundary={boundary}",
        )

    # ---- eventi in tempo reale (SSE) ----------------------------------
    @app.route("/events")
    def events():
        def stream_events():
            q = bus.subscribe()
            # Stato iniziale appena ci si collega.
            import json
            yield f"data: {json.dumps({'type': 'status', 'ts': time.time(), 'data': monitor.status()})}\n\n"
            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                        yield f"data: {msg}\n\n"
                    except Exception:
                        # keep-alive per non far cadere la connessione
                        yield ": keep-alive\n\n"
            finally:
                bus.unsubscribe(q)

        return Response(stream_events(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- stato e comandi ----------------------------------------------
    @app.route("/api/status")
    def api_status():
        return jsonify(monitor.status())

    @app.route("/api/motion", methods=["POST"])
    def api_motion():
        data = request.get_json(silent=True) or {}
        if "enabled" in data:
            monitor.set_enabled(bool(data["enabled"]))
        if "sensitivity" in data:
            try:
                monitor.set_sensitivity(int(data["sensitivity"]))
            except (TypeError, ValueError):
                return jsonify({"error": "sensitivity non valida"}), 400
        return jsonify(monitor.status())

    # ---- ninna nanne ---------------------------------------------------
    @app.route("/api/lullabies")
    def api_lullabies():
        return jsonify(library.list())

    @app.route("/lullabies/<path:name>")
    def lullaby_file(name):
        path = library.path_for(name)
        if not path:
            return jsonify({"error": "file non trovato"}), 404
        return send_file(path)

    @app.route("/api/lullabies/play-local", methods=["POST"])
    def api_play_local():
        data = request.get_json(silent=True) or {}
        name = data.get("name", "")
        ok = library.play_local(name)
        if not ok:
            return jsonify({"error": "impossibile riprodurre (file o lettore mancante)"}), 400
        return jsonify({"playing": name})

    @app.route("/api/lullabies/stop-local", methods=["POST"])
    def api_stop_local():
        library.stop_local()
        return jsonify({"stopped": True})

    return app
