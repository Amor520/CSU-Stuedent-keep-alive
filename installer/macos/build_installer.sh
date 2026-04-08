#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD_DIR="$ROOT_DIR/build/macos"
VENV_DIR="$BUILD_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VERSION="${VERSION:-1.4.6}"
PKG_ID="cn.csu.autorelogin"
APP_SUPPORT_SUBDIR="CSUStudentWiFi"
PKGROOT="$BUILD_DIR/pkgroot"
PAYLOAD_BASE="$PKGROOT/Library/Application Support/$APP_SUPPORT_SUBDIR"
DIST_DIR="$ROOT_DIR/dist"
BIN_NAME="csu-auto-relogin"
SETUP_BIN_NAME="csu-auto-relogin-setup"
PKG_NAME="CSUStudentWiFi-${VERSION}.pkg"
ICON_DIR="$BUILD_DIR/icon"
ICON_SOURCE="$ICON_DIR/AppIcon-1024.png"
ICONSET_DIR="$ICON_DIR/AppIcon.iconset"
ICON_ICNS="$ICON_DIR/AppIcon.icns"

echo "[1/6] Preparing build directories"
rm -rf "$BUILD_DIR"
mkdir -p \
  "$BUILD_DIR" \
  "$DIST_DIR" \
  "$PAYLOAD_BASE/bin" \
  "$ICON_DIR"

echo "[2/6] Preparing build virtualenv"
"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
HTTPS_PROXY= HTTP_PROXY= ALL_PROXY= NO_PROXY= python -m pip install --upgrade pip >/dev/null
HTTPS_PROXY= HTTP_PROXY= ALL_PROXY= NO_PROXY= python -m pip install -r "$ROOT_DIR/requirements.txt" pyinstaller >/dev/null

echo "[3/6] Building standalone binary"
pyinstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name "$BIN_NAME" \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/build" \
  --specpath "$BUILD_DIR" \
  "$ROOT_DIR/auto_relogin.py" >/dev/null

echo "[3.5/6] Building native setup app"
swiftc \
  -parse-as-library \
  "$ROOT_DIR/setup_gui.swift" \
  -o "$BUILD_DIR/dist/$SETUP_BIN_NAME"

echo "[3.7/6] Rendering app icon"
swift "$ROOT_DIR/installer/macos/support/generate_app_icon.swift" "$ICON_SOURCE"
mkdir -p "$ICONSET_DIR"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$ICON_SOURCE" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
  doubled=$((size * 2))
  sips -z "$doubled" "$doubled" "$ICON_SOURCE" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET_DIR" -o "$ICON_ICNS"

echo "[4/6] Preparing package payload"
cp "$BUILD_DIR/dist/$BIN_NAME" "$PAYLOAD_BASE/bin/$BIN_NAME"
cp "$BUILD_DIR/dist/$SETUP_BIN_NAME" "$PAYLOAD_BASE/bin/$SETUP_BIN_NAME"
cp "$ICON_ICNS" "$PAYLOAD_BASE/AppIcon.icns"
cp "$ROOT_DIR/config.example.toml" "$PAYLOAD_BASE/config.example.toml"
cp "$ROOT_DIR/README.md" "$PAYLOAD_BASE/README.md"
cp "$ROOT_DIR/installer/macos/support/setup_launch_agent.sh" "$PAYLOAD_BASE/setup_launch_agent.sh"
cp "$ROOT_DIR/installer/macos/support/disable_launch_agent.sh" "$PAYLOAD_BASE/disable_launch_agent.sh"
cp "$ROOT_DIR/installer/macos/support/open_config.sh" "$PAYLOAD_BASE/open_config.sh"
cp "$ROOT_DIR/installer/macos/support/open_setup_wizard.sh" "$PAYLOAD_BASE/open_setup_wizard.sh"
chmod 755 \
  "$PAYLOAD_BASE/bin/$BIN_NAME" \
  "$PAYLOAD_BASE/bin/$SETUP_BIN_NAME" \
  "$PAYLOAD_BASE/setup_launch_agent.sh" \
  "$PAYLOAD_BASE/disable_launch_agent.sh" \
  "$PAYLOAD_BASE/open_config.sh" \
  "$PAYLOAD_BASE/open_setup_wizard.sh"

echo "[5/6] Building pkg"
pkgbuild \
  --root "$PKGROOT" \
  --identifier "$PKG_ID" \
  --version "$VERSION" \
  --install-location "/" \
  --scripts "$ROOT_DIR/installer/macos/pkgscripts" \
  "$DIST_DIR/$PKG_NAME" >/dev/null

echo "[6/6] Done"
echo "Installer: $DIST_DIR/$PKG_NAME"
