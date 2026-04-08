#!/bin/bash
set -euo pipefail

APP_SUPPORT_DIR="/Library/Application Support/CSUStudentWiFi"
APP_BUNDLE="/Applications/CSUStudentWiFi.app"
SETUP_BIN="$APP_SUPPORT_DIR/bin/csu-auto-relogin-setup"

if [[ -d "$APP_BUNDLE" ]]; then
  exec open "$APP_BUNDLE"
fi

if [[ ! -x "$SETUP_BIN" ]]; then
  echo "Setup wizard binary not found: $SETUP_BIN"
  exit 1
fi

exec "$SETUP_BIN"
