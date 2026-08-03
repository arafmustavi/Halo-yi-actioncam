"""
Halo -- minimalist gallery, capture, bulk-download & on-device AI for the Xiaomi YI Action Camera.
This build adds performance features that stop the camera's tiny embedded HTTP
server from being overwhelmed:

Features in this build:
  * Paginated gallery (cheap on the camera) + server thumbnail cache
  * Concurrency cap so the camera's tiny HTTP server isn't overwhelmed
  * "Download All" -> saves media to a local folder with live progress
  * "Run AI" -> downloads photos locally, runs YOLO, saves annotated copies,
                streams side-by-side results with a progress bar
  * Dark mode is purely client-side (see static/app.js + style.css)
  * PAGINATION      -> /api/gallery?page=&page_size=  returns a metadata slice
                       + total + has_more (no thumbnails touched server-side).
  * FILE-LIST CACHE -> the DCIM listing is scraped once and cached (short TTL)
                       so paging doesn't re-walk the camera every request.
  * THUMBNAIL CACHE -> /thumb downscales each photo ONCE with Pillow and stores
                       it on disk; every later view is instant & camera-free.
  * CONCURRENCY CAP -> a semaphore limits how many requests hit the camera at
                       once, so a burst of thumbnails can't choke it.

Runs from source (python app.py) and as a frozen PyInstaller .exe.
"""

import os
import re
import sys
import time
import socket
import threading
import webbrowser
from io import BytesIO
from urllib.parse import unquote, quote

import requests
from flask import (Flask, Response, jsonify, render_template, request, abort,
                   send_file, send_from_directory)

from yi_camera import YiCamera, YiCameraError

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False


# ---------------------------------------------------------------------------
# Paths (frozen-aware)
# ---------------------------------------------------------------------------
def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def writable_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CAMERA_IP     = os.environ.get("YI_IP", "192.168.42.1")
PAGE_SIZE     = int(os.environ.get("HALO_PAGE_SIZE", "24"))
THUMB_PX      = int(os.environ.get("HALO_THUMB_PX", "320"))
LIST_TTL      = 15
MAX_CAMERA_IO = 3

BASE_DIR      = writable_dir()
CACHE_DIR     = os.environ.get("HALO_CACHE_DIR") or os.path.join(BASE_DIR, "thumb_cache")
DOWNLOADS_DIR = os.environ.get("HALO_DOWNLOADS_DIR") or os.path.join(BASE_DIR, "Halo_Downloads")
AI_DIR        = os.environ.get("HALO_AI_DIR") or os.path.join(BASE_DIR, "Halo_AI")
AI_ORIG_DIR   = os.path.join(AI_DIR, "originals")
AI_ANNO_DIR   = os.path.join(AI_DIR, "annotated")
for d in (CACHE_DIR, DOWNLOADS_DIR, AI_ORIG_DIR, AI_ANNO_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__,
            template_folder=resource_path("templates"),
            static_folder=resource_path("static"))

camera = YiCamera(ip=CAMERA_IP)
_state = {"recording": False, "rec_started": None}
_camera_sema = threading.Semaphore(MAX_CAMERA_IO)
_list_cache = {"ts": 0, "items": []}
_list_lock = threading.Lock()


def ensure_connected():
    if not camera.connected:
        camera.connect()


def api_error(exc, code=502):
    return jsonify({"ok": False, "error": str(exc)}), code


# ---------------------------------------------------------------------------
# Camera file listing (scraped once, cached)
# ---------------------------------------------------------------------------
MEDIA_RE = re.compile(r'\.(?:jpg|jpeg|mp4|mov)$', re.IGNORECASE)


def _scrape_dir(url):
    files, dirs = [], []
    try:
        with _camera_sema:
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


def _list_media(force=False):
    now = time.time()
    with _list_lock:
        if not force and (now - _list_cache["ts"] < LIST_TTL) and _list_cache["items"]:
            return _list_cache["items"]
    root = f"http://{CAMERA_IP}/DCIM/"
    all_files = []
    files, dirs = _scrape_dir(root)
    all_files += files
    for d in dirs:
        f2, _ = _scrape_dir(d)
        all_files += f2
    items = []
    for u in sorted(set(all_files), reverse=True):
        name = u.rsplit("/", 1)[-1]
        is_video = u.lower().endswith((".mp4", ".mov"))
        items.append({
            "url": u, "name": name,
            "type": "video" if is_video else "photo",
            "src": "/thumb?url=" + quote(u, safe=""),
            "full": "/media?url=" + quote(u, safe=""),
        })
    with _list_lock:
        _list_cache["ts"] = now
        _list_cache["items"] = items
    return items


def _filtered(items, flt):
    if flt in ("photo", "video"):
        return [m for m in items if m["type"] == flt]
    return items


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", camera_ip=CAMERA_IP)


@app.route("/ai")
def ai_page():
    return render_template("ai.html", camera_ip=CAMERA_IP)


# ---------------------------------------------------------------------------
# Status / gallery / media
# ---------------------------------------------------------------------------
@app.route("/api/status")
def api_status():
    try:
        ensure_connected()
        bat = camera.battery()
        rec_secs = int(time.time() - _state["rec_started"]) if _state["rec_started"] else 0
        return jsonify({"ok": True, "connected": True, "battery": bat,
                        "recording": _state["recording"], "rec_secs": rec_secs,
                        "ip": CAMERA_IP})
    except YiCameraError as exc:
        return jsonify({"ok": False, "connected": False, "error": str(exc)})


@app.route("/api/gallery")
def api_gallery():
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = max(1, min(100, int(request.args.get("page_size", PAGE_SIZE))))
        flt = request.args.get("filter", "all")
        force = request.args.get("refresh") == "1"
        items = _filtered(_list_media(force=force), flt)
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = items[start:end]
        return jsonify({"ok": True, "page": page, "page_size": page_size,
                        "total": total, "returned": len(page_items),
                        "has_more": end < total, "media": page_items})
    except Exception as exc:  # noqa
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/thumb")
def thumb():
    url = request.args.get("url", "")
    if not url.startswith(f"http://{CAMERA_IP}"):
        abort(400, "Only camera URLs are allowed.")
    name = unquote(url.rsplit("/", 1)[-1])
    if name.lower().endswith((".mp4", ".mov")):
        return ("", 204)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    cache_file = os.path.join(CACHE_DIR, f"{THUMB_PX}_{safe}.jpg")
    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 0:
        return send_file(cache_file, mimetype="image/jpeg")
    if not PIL_OK:
        return _proxy(url)
    try:
        with _camera_sema:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
        img = Image.open(BytesIO(r.content))
        img.draft("RGB", (THUMB_PX, THUMB_PX))
        img = img.convert("RGB")
        img.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
        img.save(cache_file, "JPEG", quality=82, optimize=True)
        return send_file(cache_file, mimetype="image/jpeg")
    except Exception as exc:  # noqa
        return api_error(exc)


def _proxy(url, as_attachment=False):
    headers = {}
    rng = request.headers.get("Range")
    if rng:
        headers["Range"] = rng
    try:
        with _camera_sema:
            r = requests.get(url, stream=True, timeout=25, headers=headers)
    except requests.RequestException as exc:
        return api_error(exc)
    resp = Response(r.iter_content(chunk_size=32768), status=r.status_code,
                    content_type=r.headers.get("Content-Type", "application/octet-stream"))
    for h in ("Content-Length", "Content-Range", "Accept-Ranges"):
        if h in r.headers:
            resp.headers[h] = r.headers[h]
    if as_attachment:
        name = unquote(url.rsplit("/", 1)[-1])
        resp.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


@app.route("/media")
def media_proxy():
    url = request.args.get("url", "")
    if not url.startswith(f"http://{CAMERA_IP}"):
        abort(400, "Only camera URLs are allowed.")
    return _proxy(url)


@app.route("/api/download")
def api_download():
    url = request.args.get("url", "")
    if not url.startswith(f"http://{CAMERA_IP}"):
        abort(400, "Only camera URLs are allowed.")
    return _proxy(url, as_attachment=True)


# ---------------------------------------------------------------------------
# Capture / record
# ---------------------------------------------------------------------------
@app.route("/api/capture", methods=["POST"])
def api_capture():
    try:
        ensure_connected()
        path = camera.take_photo()
        _list_cache["ts"] = 0
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
        _list_cache["ts"] = 0
        return jsonify({"ok": True, "recording": False})
    except YiCameraError as exc:
        return api_error(exc)


# ---------------------------------------------------------------------------
# Bulk "Download All" -> local folder, with progress
# ---------------------------------------------------------------------------
_dl_job = {"running": False, "done": 0, "total": 0, "current": "",
           "errors": [], "folder": DOWNLOADS_DIR, "finished": False}
_dl_lock = threading.Lock()


def _download_one(url, dest):
    with _camera_sema:
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        tmp = dest + ".part"
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                fh.write(chunk)
        os.replace(tmp, dest)


def _run_download_all(items, subfolder):
    target = os.path.join(DOWNLOADS_DIR, subfolder) if subfolder else DOWNLOADS_DIR
    os.makedirs(target, exist_ok=True)
    with _dl_lock:
        _dl_job.update(running=True, done=0, total=len(items), current="",
                       errors=[], folder=target, finished=False)
    for m in items:
        with _dl_lock:
            _dl_job["current"] = m["name"]
        dest = os.path.join(target, m["name"])
        try:
            if not (os.path.exists(dest) and os.path.getsize(dest) > 0):
                _download_one(m["url"], dest)
        except Exception as exc:  # noqa
            with _dl_lock:
                _dl_job["errors"].append({"name": m["name"], "error": str(exc)})
        with _dl_lock:
            _dl_job["done"] += 1
    with _dl_lock:
        _dl_job["running"] = False
        _dl_job["finished"] = True
        _dl_job["current"] = ""


@app.route("/api/download-all/start", methods=["POST"])
def api_download_all_start():
    with _dl_lock:
        if _dl_job["running"]:
            return jsonify({"ok": False, "error": "A download is already running."}), 409
    try:
        flt = request.args.get("filter", "all")
        items = _filtered(_list_media(), flt)
        if not items:
            return jsonify({"ok": False, "error": "Nothing to download."})
        stamp = time.strftime("%Y%m%d_%H%M%S")
        threading.Thread(target=_run_download_all, args=(items, stamp), daemon=True).start()
        return jsonify({"ok": True, "total": len(items),
                        "folder": os.path.join(DOWNLOADS_DIR, stamp)})
    except Exception as exc:  # noqa
        return api_error(exc)


@app.route("/api/download-all/progress")
def api_download_all_progress():
    with _dl_lock:
        return jsonify({"ok": True, **_dl_job})


# ---------------------------------------------------------------------------
# AI job (YOLO)  -> download originals, run detection, save annotated
# ---------------------------------------------------------------------------
import yolo_detect  # noqa: E402

_ai_job = {"running": False, "done": 0, "total": 0, "current": "",
           "results": [], "error": None, "finished": False}
_ai_lock = threading.Lock()


def _run_ai(items):
    with _ai_lock:
        _ai_job.update(running=True, done=0, total=len(items), current="",
                       results=[], error=None, finished=False)

    ok, msg = yolo_detect.available()
    if not ok:
        with _ai_lock:
            _ai_job.update(running=False, finished=True, error=msg)
        return

    for m in items:
        name = m["name"]
        with _ai_lock:
            _ai_job["current"] = name
        base, _ext = os.path.splitext(name)
        orig_path = os.path.join(AI_ORIG_DIR, name)
        anno_path = os.path.join(AI_ANNO_DIR, base + "_annotated.jpg")
        entry = {"name": name,
                 "original": "/ai/original/" + quote(name),
                 "annotated": "/ai/annotated/" + quote(base + "_annotated.jpg"),
                 "ok": False, "count": 0, "summary": {}, "error": None}
        try:
            if not (os.path.exists(orig_path) and os.path.getsize(orig_path) > 0):
                _download_one(m["url"], orig_path)
            res = yolo_detect.detect(orig_path, anno_path)
            if res.get("ok"):
                entry.update(ok=True, count=res["count"], summary=res["summary"])
            else:
                entry["error"] = res.get("error", "detection failed")
        except Exception as exc:  # noqa
            entry["error"] = str(exc)
        with _ai_lock:
            _ai_job["results"].append(entry)
            _ai_job["done"] += 1

    with _ai_lock:
        _ai_job["running"] = False
        _ai_job["finished"] = True
        _ai_job["current"] = ""


@app.route("/api/ai/available")
def api_ai_available():
    ok, msg = yolo_detect.available()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/ai/start", methods=["POST"])
def api_ai_start():
    with _ai_lock:
        if _ai_job["running"]:
            return jsonify({"ok": False, "error": "AI run already in progress."}), 409
    flt = request.args.get("filter", "photo")   # photos only by default
    limit = request.args.get("limit")
    items = [m for m in _list_media() if m["type"] == "photo"] if flt == "photo" \
        else _filtered(_list_media(), flt)
    if limit:
        try:
            items = items[: int(limit)]
        except ValueError:
            pass
    if not items:
        return jsonify({"ok": False, "error": "No photos to analyze."})
    threading.Thread(target=_run_ai, args=(items,), daemon=True).start()
    return jsonify({"ok": True, "total": len(items)})


@app.route("/api/ai/progress")
def api_ai_progress():
    with _ai_lock:
        return jsonify({"ok": True, **_ai_job})


@app.route("/ai/original/<path:name>")
def ai_original(name):
    return send_from_directory(AI_ORIG_DIR, name)


@app.route("/ai/annotated/<path:name>")
def ai_annotated(name):
    return send_from_directory(AI_ANNO_DIR, name)


# ---------------------------------------------------------------------------
# Cache housekeeping
# ---------------------------------------------------------------------------
@app.route("/api/cache/clear", methods=["POST"])
def api_cache_clear():
    n = 0
    for f in os.listdir(CACHE_DIR):
        try:
            os.remove(os.path.join(CACHE_DIR, f)); n += 1
        except OSError:
            pass
    return jsonify({"ok": True, "removed": n})


@app.route("/api/paths")
def api_paths():
    return jsonify({"ok": True, "downloads": DOWNLOADS_DIR,
                    "ai": AI_DIR, "cache": CACHE_DIR})


# ---------------------------------------------------------------------------
# Launcher
# ---------------------------------------------------------------------------
def _find_free_port(preferred=5000):
    for port in (preferred, 5001, 5050, 8000, 8080):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    port = _find_free_port(int(os.environ.get("HALO_PORT", "5000")))
    url = f"http://127.0.0.1:{port}"
    line = "=" * 54
    print(f"\n{line}\n   Halo  -  Camera Gallery + AI\n{line}")
    print(f"   Running at : {url}")
    print( "   Camera Wi-Fi: YDXJ_xxxxxxx  (pass 1234567890)")
    print(f"   Downloads  : {DOWNLOADS_DIR}")
    print(f"   AI outputs : {AI_DIR}")
    print( "   Quit        : close this window")
    print(line + "\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve
        serve(app, host="127.0.0.1", port=port, threads=8, _quiet=True)
    except Exception:
        app.run(host="127.0.0.1", port=port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
