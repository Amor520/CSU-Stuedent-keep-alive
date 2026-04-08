#!/bin/bash
set -euo pipefail

LAUNCH_AGENT_LABEL="cn.csu.autorelogin"

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
  echo "Unable to determine target user; nothing to disable."
  exit 0
fi

USER_HOME="$(resolve_user_home "$TARGET_USER")"
PLIST_PATH="$USER_HOME/Library/LaunchAgents/${LAUNCH_AGENT_LABEL}.plist"
USER_UID="$(id -u "$TARGET_USER")"

if [[ -f "$PLIST_PATH" ]]; then
  if [[ "$(id -u)" -eq 0 ]]; then
    launchctl bootout "gui/$USER_UID" "$PLIST_PATH" >/dev/null 2>&1 || true
  else
    launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
  fi
  rm -f "$PLIST_PATH"
fi

echo "LaunchAgent removed."
