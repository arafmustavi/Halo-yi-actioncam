"""
Halo -- a minimalist gallery & capture app for the Xiaomi YI Action Camera.

This build adds performance features that stop the camera's tiny embedded HTTP
server from being overwhelmed:

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
from flask import Flask, Response, jsonify, render_template, request, abort, send_file

from yi_camera import YiCamera, YiCameraError

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False


# ---------------------------------------------------------------------------
# Frozen-aware paths (works from source AND from a PyInstaller build)
# ---------------------------------------------------------------------------
def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def writable_dir():
    """A place we can write the thumbnail cache (next to the exe / script)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CAMERA_IP     = os.environ.get("YI_IP", "192.168.42.1")
PAGE_SIZE     = int(os.environ.get("HALO_PAGE_SIZE", "24"))
THUMB_PX      = int(os.environ.get("HALO_THUMB_PX", "320"))
LIST_TTL      = 15          # seconds to trust the cached DCIM listing
MAX_CAMERA_IO = 3           # max simultaneous requests to the camera

# Cache dir can be redirected (e.g. Android points it at app-private storage).
CACHE_DIR = os.environ.get("HALO_CACHE_DIR") or os.path.join(writable_dir(), "thumb_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
)

camera = YiCamera(ip=CAMERA_IP)
_state = {"recording": False, "rec_started": None}

# Global throttle: never let more than MAX_CAMERA_IO hits reach the camera.
_camera_sema = threading.Semaphore(MAX_CAMERA_IO)

# Cached file listing (populated by _list_media, refreshed after LIST_TTL).
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
    """Return the full, sorted media list (cached for LIST_TTL seconds)."""
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
            "url": u,
            "name": name,
            "type": "video" if is_video else "photo",
            "src": "/thumb?url=" + quote(u, safe=""),      # cached thumbnail
            "full": "/media?url=" + quote(u, safe=""),      # full-res proxy
        })
    with _list_lock:
        _list_cache["ts"] = now
        _list_cache["items"] = items
    return items


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
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


@app.route("/api/gallery")
def api_gallery():
    """
    Paginated gallery metadata. Query params:
      page       (1-based, default 1)
      page_size  (default PAGE_SIZE)
      filter     (all | photo | video, default all)
      refresh    (1 to force re-scrape the camera)
    Returns only the slice for the requested page -- NO thumbnails are fetched
    here, so this call is always cheap on the camera.
    """
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = max(1, min(100, int(request.args.get("page_size", PAGE_SIZE))))
        flt = request.args.get("filter", "all")
        force = request.args.get("refresh") == "1"

        items = _list_media(force=force)
        if flt in ("photo", "video"):
            items = [m for m in items if m["type"] == flt]

        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = items[start:end]

        return jsonify({
            "ok": True,
            "page": page,
            "page_size": page_size,
            "total": total,
            "returned": len(page_items),
            "has_more": end < total,
            "media": page_items,
        })
    except Exception as exc:  # noqa
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/thumb")
def thumb():
    """
    Return a small, cached thumbnail for a camera photo. First request for a
    given file downscales it with Pillow and writes it to disk; every later
    request is served straight from disk (the camera is never touched again).
    Videos have no server thumbnail -> the UI shows a poster tile instead.
    """
    url = request.args.get("url", "")
    if not url.startswith(f"http://{CAMERA_IP}"):
        abort(400, "Only camera URLs are allowed.")
    name = unquote(url.rsplit("/", 1)[-1])

    # videos: no cheap server-side thumbnail; let the client show a placeholder
    if name.lower().endswith((".mp4", ".mov")):
        return ("", 204)

    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    cache_file = os.path.join(CACHE_DIR, f"{THUMB_PX}_{safe}.jpg")

    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 0:
        return send_file(cache_file, mimetype="image/jpeg")

    if not PIL_OK:
        # No Pillow -> fall back to proxying the full image (still works).
        return _proxy(url)

    try:
        with _camera_sema:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
        img = Image.open(BytesIO(r.content))
        img.draft("RGB", (THUMB_PX, THUMB_PX))     # fast partial decode
        img = img.convert("RGB")
        img.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
        img.save(cache_file, "JPEG", quality=82, optimize=True)
        return send_file(cache_file, mimetype="image/jpeg")
    except Exception as exc:  # noqa
        return api_error(exc)


def _proxy(url, as_attachment=False):
    """Stream a camera file through the app (range-aware for video seeking)."""
    headers = {}
    rng = request.headers.get("Range")
    if rng:
        headers["Range"] = rng
    try:
        with _camera_sema:
            r = requests.get(url, stream=True, timeout=25, headers=headers)
    except requests.RequestException as exc:
        return api_error(exc)
    resp = Response(r.iter_content(chunk_size=32768),
                    status=r.status_code,
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


@app.route("/api/capture", methods=["POST"])
def api_capture():
    try:
        ensure_connected()
        path = camera.take_photo()
        _list_cache["ts"] = 0                     # invalidate listing cache
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


@app.route("/api/cache/clear", methods=["POST"])
def api_cache_clear():
    """Delete all cached thumbnails (housekeeping)."""
    n = 0
    for f in os.listdir(CACHE_DIR):
        try:
            os.remove(os.path.join(CACHE_DIR, f))
            n += 1
        except OSError:
            pass
    return jsonify({"ok": True, "removed": n})


@app.route("/api/cache/info")
def api_cache_info():
    total = 0
    count = 0
    for f in os.listdir(CACHE_DIR):
        try:
            total += os.path.getsize(os.path.join(CACHE_DIR, f))
            count += 1
        except OSError:
            pass
    return jsonify({"ok": True, "count": count,
                    "bytes": total, "mb": round(total / 1048576, 2)})


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
    line = "=" * 52
    print(f"\n{line}\n   Halo  -  Camera Gallery\n{line}")
    print(f"   Running at : {url}")
    print( "   Camera Wi-Fi: YDXJ_xxxxxxx  (pass 1234567890)")
    print(f"   Thumb cache : {CACHE_DIR}")
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
