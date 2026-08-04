#!/usr/bin/env bash
# ============================================================
#  Halo — portable binary builder (macOS / Linux)
#     ./build.sh        -> LITE build (gallery)      dist/Halo
#     ./build.sh ai     -> FULL build (with YOLO)    dist/Halo/Halo
# ============================================================
set -e
cd "$(dirname "$0")"

MODE="lite"
[ "$1" = "ai" ] && MODE="ai"
[ "$1" = "full" ] && MODE="ai"

echo "============================================================"
echo "   Halo portable builder   [mode: $MODE]"
echo "============================================================"

command -v python3 >/dev/null 2>&1 || { echo "[ERROR] python3 not found"; exit 1; }

python3 -m venv .venv-build
# shellcheck disable=SC1091
source .venv-build/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install flask requests waitress pillow pyinstaller >/dev/null

if [ "$MODE" = "ai" ]; then
  echo "Installing AI stack (ultralytics + torch)... this is large."
  pip install ultralytics
  echo "Building FULL AI app (one-folder)..."
  pyinstaller Halo-AI.spec --noconfirm --clean
  OUT="dist/Halo/Halo"
else
  echo "Building LITE app (single file)..."
  pyinstaller Halo.spec --noconfirm --clean
  OUT="dist/Halo"
fi

echo ""
if [ -e "$OUT" ]; then
  echo "============================================================"
  echo "   SUCCESS!  ->  $OUT"
  echo "============================================================"
else
  echo "[ERROR] Build failed — see messages above."; exit 1
fi
