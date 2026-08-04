# 📦 Halo Portable Builder

Turn the Halo web app into a **portable, no-install executable**. This folder is
kept **separate** from the app source (`../halo`) so the build tooling never
clutters the app itself.

> ⚠️ A Windows `.exe` must be built **on Windows** (PyInstaller is
> platform-native). `build.bat` makes it a single double-click.

---

## Two build flavours

| Command | Output | Size | AI (YOLO)? |
|---|---|---|---|
| `build.bat`      | `dist\Halo.exe` (one file) | ~15–20 MB | ❌ Run-AI page shows an "install" hint |
| `build.bat ai`   | `dist\Halo\` (one folder)  | ~1.5–4 GB | ✅ Full on-device detection |

The **lite** build is perfect for the gallery / capture / record / download-all
features and stays tiny + instant. The **AI** build bundles Ultralytics + Torch,
so it's large — one-folder mode is used because it's far more reliable and faster
to start than cramming Torch into a single file.

---

## Prerequisites

- **Python 3.9+** on your PATH (only needed on the *build* machine — the produced
  app needs no Python).
- Internet on first build (downloads PyInstaller, and for the AI build, Torch).
- Folder layout must be:
  ```
  <parent>/
  ├── halo/               ← the app (app.py, templates/, static/, …)
  └── portable-builder/   ← you are here
  ```

## Build it

### Windows
```bat
:: LITE (gallery) — single portable Halo.exe
build.bat

:: FULL (with AI) — portable folder dist\Halo\
build.bat ai
```

### macOS / Linux
```bash
./build.sh        # lite  -> dist/Halo
./build.sh ai     # full  -> dist/Halo/Halo
```

---

## What the app does at runtime

1. Starts a local **waitress + Flask** server on a free port.
2. **Auto-opens your browser** to the Halo UI.
3. You connect the PC to the camera's `YDXJ_` Wi-Fi and use it.
4. **Downloads**, **AI outputs**, and the **thumbnail cache** are written to
   folders next to the executable:
   ```
   Halo_Downloads/   Halo_AI/originals   Halo_AI/annotated   thumb_cache/
   ```
5. Close the console window to quit.

---

## Files here

| File | Purpose |
|---|---|
| `build.bat` / `build.sh` | One-click builders (lite by default, `ai` for full) |
| `Halo.spec` | PyInstaller recipe — **lite**, single-file, AI excluded |
| `Halo-AI.spec` | PyInstaller recipe — **full**, one-folder, bundles Torch/Ultralytics |
| `README.md` | this file |

## Tips & troubleshooting

- **Smaller AI build:** the first AI run still needs the YOLO **weights**
  (`yolov8n.pt`, ~6 MB) — Ultralytics downloads them automatically. To ship
  fully offline, drop `yolov8n.pt` next to the exe after the first run.
- **SmartScreen:** an unsigned exe shows "Windows protected your PC" once →
  *More info → Run anyway*. Sign with a code-signing cert to remove it.
- **Antivirus:** one-file PyInstaller apps unpack to a temp dir on launch and can
  be heuristically flagged; the lite build is the most compatible. The AI
  one-folder build avoids the temp-unpack entirely.
- **`icon not found`:** the specs use `../halo/docs/halo.ico` if present; it's
  optional and the build still works without it.
