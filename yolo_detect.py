"""
yolo_detect.py -- on-device object detection for Halo.

Wraps Ultralytics YOLO. The model is lazy-loaded on first use (Ultralytics
auto-downloads the weights, e.g. yolov8n.pt, the first time). Everything is kept
optional so the rest of Halo runs even if YOLO isn't installed yet -- callers
get a clear, structured error instead of a crash.

Public API:
    available() -> (bool, message)
    detect(src_path, dst_path, conf=0.35) -> dict result
"""

import os
import threading

_MODEL = None
_MODEL_LOCK = threading.Lock()
_MODEL_NAME = os.environ.get("HALO_YOLO_MODEL", "yolov8n.pt")


def available():
    """Return (ok, message). ok=True means detect() can run."""
    try:
        import ultralytics  # noqa: F401
    except Exception as exc:  # pragma: no cover
        return False, (
            "Ultralytics is not installed. Install it with "
            "`pip install ultralytics` to enable AI detection. "
            f"({exc})"
        )
    return True, "ready"


def _get_model():
    """Load (once) and cache the YOLO model."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from ultralytics import YOLO
            # Ultralytics downloads the weights automatically if missing.
            _MODEL = YOLO(_MODEL_NAME)
    return _MODEL


def detect(src_path, dst_path, conf=0.35):
    """
    Run detection on `src_path`, write an annotated image to `dst_path`.

    Returns a dict:
      {
        "ok": True,
        "count": <int>,
        "detections": [{"label": str, "confidence": float}, ...],
        "summary": {"person": 2, "car": 1, ...}
      }
    or {"ok": False, "error": "..."} on failure.
    """
    ok, msg = available()
    if not ok:
        return {"ok": False, "error": msg}

    try:
        model = _get_model()
        results = model(src_path, conf=conf, verbose=False)
        r = results[0]

        # Draw boxes/labels and save the annotated frame.
        annotated = r.plot()  # numpy BGR array
        try:
            import cv2
            cv2.imwrite(dst_path, annotated)
        except Exception:
            # Fallback to PIL if cv2 isn't available for writing.
            from PIL import Image
            Image.fromarray(annotated[:, :, ::-1]).save(dst_path, "JPEG", quality=90)

        names = r.names
        detections = []
        summary = {}
        if r.boxes is not None:
            for b in r.boxes:
                cls = int(b.cls[0])
                label = names.get(cls, str(cls)) if isinstance(names, dict) else names[cls]
                confidence = float(b.conf[0])
                detections.append({"label": label, "confidence": round(confidence, 3)})
                summary[label] = summary.get(label, 0) + 1

        return {
            "ok": True,
            "count": len(detections),
            "detections": detections,
            "summary": summary,
        }
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"Detection failed: {exc}"}
