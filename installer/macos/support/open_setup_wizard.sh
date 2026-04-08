#!/bin/bash
set -euo pipefail

APP_SUPPORT_DIR="/Library/Application Support/CSUStudentWiFi"
SETUP_BIN="$APP_SUPPORT_DIR/bin/csu-auto-relogin-setup"

if [[ ! -x "$SETUP_BIN" ]]; then
  echo "Setup wizard binary not found: $SETUP_BIN"
  exit 1
fi

exec "$SETUP_BIN"
