"""Server web: espone la webapp (PWA), il wizard di configurazione, lo stream
video MJPEG, gli eventi in tempo reale (SSE) e le ninna nanne.

Tutto viaggia sulla rete locale: nessun dato esce da casa, nessun cloud.
"""

from __future__ import annotations

import json
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

from . import qr as qrgen
from .config import CameraConfig
from .controller import Controller
from .netinfo import app_url

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def create_app(controller: Controller) -> Flask:
    app = Flask(__name__, static_folder=None)
    bus = controller.bus
    library = controller.library

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
                cam = controller.camera
                last_id = cam.wait_for_frame(last_id, timeout=2.0)
                jpeg = cam.latest_jpeg()
                if jpeg is None:
                    time.sleep(0.1)
                    continue
                yield (
                    b"--" + boundary.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg + b"\r\n"
                )

        return Response(generate(), mimetype=f"multipart/x-mixed-replace; boundary={boundary}")

    # ---- eventi in tempo reale (SSE) ----------------------------------
    @app.route("/events")
    def events():
        def stream_events():
            q = bus.subscribe()
            yield f"data: {json.dumps({'type': 'status', 'ts': time.time(), 'data': controller.monitor.status()})}\n\n"
            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                        yield f"data: {msg}\n\n"
                    except Exception:
                        yield ": keep-alive\n\n"
            finally:
                bus.unsubscribe(q)

        return Response(stream_events(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- indirizzo + QR per aprire su un altro dispositivo ------------
    @app.route("/api/url")
    def api_url():
        url = app_url(controller.config.server.port)
        return jsonify({"url": url, "qr": qrgen.HAS_QR})

    @app.route("/qr.svg")
    def qr_svg():
        if not qrgen.HAS_QR:
            return jsonify({"error": "modulo qrcode non installato"}), 404
        url = app_url(controller.config.server.port)
        return Response(qrgen.svg(url), mimetype="image/svg+xml")

    # ---- stato e comandi movimento ------------------------------------
    @app.route("/api/status")
    def api_status():
        st = controller.monitor.status()
        st["configured"] = controller.is_configured()
        return jsonify(st)

    @app.route("/api/motion", methods=["POST"])
    def api_motion():
        data = request.get_json(silent=True) or {}
        try:
            controller.apply_motion(data)
        except (TypeError, ValueError):
            return jsonify({"error": "valore non valido"}), 400
        return jsonify(controller.monitor.status())

    # ---- WIZARD: configurazione ---------------------------------------
    @app.route("/api/setup/status")
    def setup_status():
        c = controller.config.camera
        return jsonify({
            "configured": controller.is_configured(),
            "camera": {"ip": c.ip, "rtsp_port": c.rtsp_port,
                       "username": c.username, "stream": c.stream,
                       "rtsp_url": c.rtsp_url},
            "sensitivity": controller.config.motion.sensitivity,
        })

    @app.route("/api/setup/discover", methods=["POST"])
    def setup_discover():
        return jsonify({"cameras": controller.discover()})

    @app.route("/api/setup/test", methods=["POST"])
    def setup_test():
        data = request.get_json(silent=True) or {}
        cam = CameraConfig(
            ip=str(data.get("ip", "")).strip(),
            rtsp_port=int(data.get("rtsp_port", 554) or 554),
            username=str(data.get("username", "")).strip(),
            password=str(data.get("password", "") or ""),
            stream=str(data.get("stream", "sub") or "sub"),
            rtsp_url=str(data.get("rtsp_url", "") or ""),
        )
        return jsonify(controller.test_camera(cam))

    @app.route("/api/setup/save", methods=["POST"])
    def setup_save():
        data = request.get_json(silent=True) or {}
        try:
            controller.apply_camera(data)
        except (TypeError, ValueError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True})

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

    @app.route("/api/lullabies/upload", methods=["POST"])
    def api_lullaby_upload():
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "nessun file"}), 400
        f = request.files["file"]
        res = library.save_upload(f.filename, f)
        return (jsonify(res), 200) if res.get("ok") else (jsonify(res), 400)

    @app.route("/api/lullabies/<path:name>", methods=["DELETE"])
    def api_lullaby_delete(name):
        return (jsonify({"ok": True}) if library.delete(name)
                else (jsonify({"ok": False, "error": "file non trovato"}), 404))

    @app.route("/api/lullabies/play-local", methods=["POST"])
    def api_play_local():
        data = request.get_json(silent=True) or {}
        ok = library.play_local(data.get("name", ""))
        if not ok:
            return jsonify({"error": "impossibile riprodurre (file o lettore mancante)"}), 400
        return jsonify({"playing": data.get("name")})

    @app.route("/api/lullabies/stop-local", methods=["POST"])
    def api_stop_local():
        library.stop_local()
        return jsonify({"stopped": True})

    return app
