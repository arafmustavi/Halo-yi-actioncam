# -*- mode: python ; coding: utf-8 -*-
"""
Halo.spec  --  LITE portable build (gallery + capture + record + download-all).

Produces a single, small, portable  dist/Halo.exe  (~15-20 MB). This build
EXCLUDES the heavy AI stack (torch / ultralytics / opencv) so it stays tiny and
starts instantly. The "Run AI" page still loads and will simply tell the user to
use the AI build if Ultralytics isn't present.

For the full AI-capable build, use Halo-AI.spec instead.

Run from the portable-builder/ folder (with ../halo alongside it):
    pyinstaller Halo.spec --noconfirm --clean
"""

import os

HALO_SRC = os.path.abspath(os.path.join(os.getcwd(), ".."))

block_cipher = None

a = Analysis(
    [os.path.join(HALO_SRC, "app.py")],
    pathex=[HALO_SRC],
    binaries=[],
    datas=[
        (os.path.join(HALO_SRC, "templates"), "templates"),
        (os.path.join(HALO_SRC, "static"), "static"),
    ],
    hiddenimports=["waitress", "flask", "jinja2", "requests", "PIL"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # keep the lite build tiny — no AI stack
        "torch", "torchvision", "ultralytics", "cv2", "numpy.tests",
        "matplotlib", "pandas", "scipy", "PyQt5", "PySide2",
        "tkinter", "test", "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="Halo",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    upx_exclude=[], runtime_tmpdir=None, console=True,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=os.path.join(HALO_SRC, "docs", "halo.ico") if os.path.exists(
        os.path.join(HALO_SRC, "docs", "halo.ico")) else None,
)
