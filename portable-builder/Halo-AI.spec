# -*- mode: python ; coding: utf-8 -*-
"""
Halo-AI.spec  --  FULL portable build WITH on-device YOLO detection.

Bundles Ultralytics + Torch + OpenCV so "Run AI" works with no extra install.
Because Torch is large, this uses ONE-FOLDER mode (a folder you zip and ship)
rather than one-file: it's far more reliable for big native libs and starts
much faster. Expect the output folder to be large (often 1.5-4 GB).

Run from the portable-builder/ folder (with ../halo alongside it):
    pyinstaller Halo-AI.spec --noconfirm --clean
Output:  dist/Halo/  (run dist/Halo/Halo.exe)
"""

import os
from PyInstaller.utils.hooks import collect_all

HALO_SRC = os.path.abspath(os.path.join(os.getcwd(), ".."))
block_cipher = None

# Pull in everything ultralytics/torch need (data files, dylibs, submodules).
datas, binaries, hiddenimports = [], [], []
for pkg in ("ultralytics", "torch", "torchvision", "cv2"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

datas += [
    (os.path.join(HALO_SRC, "templates"), "templates"),
    (os.path.join(HALO_SRC, "static"), "static"),
]
hiddenimports += ["waitress", "flask", "jinja2", "requests", "PIL", "yolo_detect"]

a = Analysis(
    [os.path.join(HALO_SRC, "app.py")],
    pathex=[HALO_SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-folder: EXE without the binaries, then COLLECT gathers everything.
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="Halo",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=os.path.join(HALO_SRC, "docs", "halo.ico") if os.path.exists(
        os.path.join(HALO_SRC, "docs", "halo.ico")) else None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[], name="Halo",
)
