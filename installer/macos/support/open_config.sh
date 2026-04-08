#!/bin/bash
set -euo pipefail

APP_SUPPORT_DIR="/Library/Application Support/CSUStudentWiFi"

resolve_target_user() {
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER:-}" != "root" ]]; then
    printf '%s\n' "$SUDO_USER"
    return
  fi
  if [[ "$(id -u)" -eq 0 ]]; then
    stat -f '%Su' /dev/console
    return
  fi
  id -un
}

resolve_user_home() {
  dscl . -read "/Users/$1" NFSHomeDirectory | awk '{print $2}'
}

TARGET_USER="$(resolve_target_user)"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  echo "Unable to determine target user."
  exit 1
fi

USER_HOME="$(resolve_user_home "$TARGET_USER")"
USER_SUPPORT_DIR="$USER_HOME/Library/Application Support/CSUStudentWiFi"
CONFIG_PATH="$USER_SUPPORT_DIR/config.toml"

mkdir -p "$USER_SUPPORT_DIR"
if [[ ! -f "$CONFIG_PATH" ]]; then
  cp "$APP_SUPPORT_DIR/config.example.toml" "$CONFIG_PATH"
  chown "$TARGET_USER":staff "$CONFIG_PATH"
  chmod 600 "$CONFIG_PATH"
fi

open -t "$CONFIG_PATH"
