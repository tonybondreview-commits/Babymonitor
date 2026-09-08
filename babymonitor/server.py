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

import subprocess

from . import qr as qrgen
from .audio import audio_command, audio_mime
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
        st["quality"] = controller.config.camera.video_quality
        return jsonify(st)

    @app.route("/api/camera/restart", methods=["POST"])
    def api_camera_restart():
        controller.restart_camera()
        return jsonify({"ok": True})

    @app.route("/api/quality", methods=["POST"])
    def api_quality():
        data = request.get_json(silent=True) or {}
        if not controller.set_quality(str(data.get("quality", ""))):
            return jsonify({"error": "qualità non valida"}), 400
        return jsonify({"quality": controller.config.camera.video_quality})

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

    # ---- audio dalla camera (senti il bimbo) --------------------------
    @app.route("/api/audio/available")
    def audio_available():
        return jsonify({"available": controller.audio_available()})

    @app.route("/audio.mp3")
    def audio_stream():
        cam = controller.config.camera
        cmd = audio_command(cam.build_url(), cam.rtsp_transport)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, bufsize=0)
        except FileNotFoundError:
            return jsonify({"error": "ffmpeg non installato"}), 500

        def generate():
            try:
                while True:
                    chunk = proc.stdout.read(4096)
                    if not chunk:
                        break
                    yield chunk
            finally:
                if proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass

        # 200 + niente range: Safari lo riproduce come stream "dal vivo".
        return Response(generate(), status=200, mimetype=audio_mime(),
                        direct_passthrough=True,
                        headers={"Cache-Control": "no-cache, no-store",
                                 "Accept-Ranges": "none", "Connection": "close"})

    # Audio in HLS (per iPad/Safari, che lo riproduce sempre).
    @app.route("/hls/audio.m3u8")
    def hls_playlist():
        controller.hls.ensure()
        path = controller.hls.wait_for_playlist(timeout=6)
        if not path:
            return jsonify({"error": "audio non pronto"}), 503
        resp = send_file(path, mimetype="application/vnd.apple.mpegurl")
        resp.headers["Cache-Control"] = "no-cache, no-store"
        return resp

    @app.route("/hls/<path:name>")
    def hls_segment(name):
        controller.hls.touch()
        path = controller.hls.file(name)
        if not path:
            return jsonify({"error": "segmento non trovato"}), 404
        return send_file(path, mimetype="video/mp2t")

    # ---- versione (per capire se l'app e' aggiornata) -----------------
    @app.route("/api/version")
    def api_version():
        from . import __version__, __build__
        return jsonify({"version": __version__, "build": __build__})

    # ---- PTZ (movimento camera) ---------------------------------------
    @app.route("/api/ptz/available")
    def ptz_available():
        return jsonify({"available": controller.ptz_available()})

    @app.route("/api/ptz/diag")
    def ptz_diag():
        return jsonify(controller.ptz_diagnose())

    @app.route("/api/ptz", methods=["POST"])
    def ptz_move():
        data = request.get_json(silent=True) or {}
        action = str(data.get("action", ""))
        ok = controller.ptz_command(action)
        return jsonify({"ok": ok})

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

    @app.route("/api/lullabies/to-camera", methods=["POST"])
    def api_to_camera():
        data = request.get_json(silent=True) or {}
        return jsonify(controller.play_to_camera(str(data.get("name", ""))))

    @app.route("/api/lullabies/to-camera/stop", methods=["POST"])
    def api_to_camera_stop():
        controller.stop_to_camera()
        return jsonify({"ok": True})

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
