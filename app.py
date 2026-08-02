"""
Halo -- a minimalist gallery & capture app for the Xiaomi YI Action Camera.

Backend: Flask. Talks to the camera's control socket (7878) for capture/record
and its HTTP file server (80) for the gallery.

Run:  python app.py   ->  http://127.0.0.1:5000
(Laptop must be on the camera's YDXJ_ Wi-Fi.)
"""

import os
import re
import time
from urllib.parse import unquote

import requests
from flask import Flask, Response, jsonify, render_template, request, abort

from yi_camera import YiCamera, YiCameraError

CAMERA_IP = os.environ.get("YI_IP", "192.168.42.1")

app = Flask(__name__)
camera = YiCamera(ip=CAMERA_IP)
_state = {"recording": False, "rec_started": None}


def ensure_connected():
    if not camera.connected:
        camera.connect()


def api_error(exc, code=502):
    return jsonify({"ok": False, "error": str(exc)}), code


@app.route("/")
def index():
    return render_template("index.html", camera_ip=CAMERA_IP)


@app.route("/api/status")
def api_status():
    try:
        ensure_connected()
        bat = camera.battery()
        rec_secs = int(time.time() - _state["rec_started"]) if _state["rec_started"] else 0
        return jsonify({"ok": True, "connected": True,
                        "battery": bat, "recording": _state["recording"],
                        "rec_secs": rec_secs, "ip": CAMERA_IP})
    except YiCameraError as exc:
        return jsonify({"ok": False, "connected": False, "error": str(exc)})


@app.route("/api/capture", methods=["POST"])
def api_capture():
    try:
        ensure_connected()
        path = camera.take_photo()
        url = camera.http_url_for(path) if path else None
        return jsonify({"ok": True, "path": path, "url": url})
    except YiCameraError as exc:
        return api_error(exc)


@app.route("/api/record/start", methods=["POST"])
def api_record_start():
    try:
        ensure_connected()
        camera.start_recording()
        _state["recording"] = True
        _state["rec_started"] = time.time()
        return jsonify({"ok": True, "recording": True})
    except YiCameraError as exc:
        return api_error(exc)


@app.route("/api/record/stop", methods=["POST"])
def api_record_stop():
    try:
        ensure_connected()
        camera.stop_recording()
        _state["recording"] = False
        _state["rec_started"] = None
        return jsonify({"ok": True, "recording": False})
    except YiCameraError as exc:
        return api_error(exc)


# --- Gallery ---------------------------------------------------------------
MEDIA_RE = re.compile(r'\.(?:jpg|jpeg|mp4|mov)$', re.IGNORECASE)


def scrape_dir(url):
    files, dirs = [], []
    try:
        html = requests.get(url, timeout=6).text
    except requests.RequestException:
        return files, dirs
    for href in re.findall(r'href="([^"]+)"', html):
        if href in ("../", "./") or href.startswith("?"):
            continue
        full = url.rstrip("/") + "/" + href.lstrip("/")
        if href.endswith("/"):
            dirs.append(full)
        elif MEDIA_RE.search(href):
            files.append(full)
    return files, dirs


@app.route("/api/gallery")
def api_gallery():
    try:
        root = f"http://{CAMERA_IP}/DCIM/"
        all_files = []
        files, dirs = scrape_dir(root)
        all_files += files
        for d in dirs:
            f2, _ = scrape_dir(d)
            all_files += f2
        media = []
        for u in sorted(set(all_files), reverse=True):
            name = u.rsplit("/", 1)[-1]
            is_video = u.lower().endswith((".mp4", ".mov"))
            media.append({
                "url": u, "name": name,
                "type": "video" if is_video else "photo",
                "src": "/media?url=" + u,
            })
        return jsonify({"ok": True, "count": len(media), "media": media})
    except Exception as exc:  # noqa
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/media")
def media_proxy():
    url = request.args.get("url", "")
    if not url.startswith(f"http://{CAMERA_IP}"):
        abort(400, "Only camera URLs are allowed.")
    headers = {}
    rng = request.headers.get("Range")
    if rng:
        headers["Range"] = rng
    try:
        r = requests.get(url, stream=True, timeout=20, headers=headers)
    except requests.RequestException as exc:
        return api_error(exc)
    resp = Response(r.iter_content(chunk_size=16384),
                    status=r.status_code,
                    content_type=r.headers.get("Content-Type", "application/octet-stream"))
    for h in ("Content-Length", "Content-Range", "Accept-Ranges"):
        if h in r.headers:
            resp.headers[h] = r.headers[h]
    return resp


@app.route("/api/download")
def api_download():
    url = request.args.get("url", "")
    if not url.startswith(f"http://{CAMERA_IP}"):
        abort(400, "Only camera URLs are allowed.")
    name = unquote(url.rsplit("/", 1)[-1])
    try:
        r = requests.get(url, stream=True, timeout=20)
        r.raise_for_status()
    except requests.RequestException as exc:
        return api_error(exc)
    return Response(r.iter_content(chunk_size=16384),
                    content_type=r.headers.get("Content-Type", "application/octet-stream"),
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


if __name__ == "__main__":
    print("Halo -> http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
