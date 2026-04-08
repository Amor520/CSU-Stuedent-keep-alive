#!/bin/bash
set -euo pipefail

APP_SUPPORT_DIR="/Library/Application Support/CSUStudentWiFi"
LAUNCH_AGENT_LABEL="cn.csu.autorelogin"
START_INTERVAL_SECONDS="${START_INTERVAL_SECONDS:-18000}"
LOAD_IF_READY=0

if [[ "${1:-}" == "--load-if-ready" ]]; then
  LOAD_IF_READY=1
fi

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

config_is_ready() {
  local config_path="$1"
  [[ -f "$config_path" ]] || return 1
  ! grep -Eq 'replace-with-real-password|20211234567' "$config_path"
}

reload_launch_agent() {
  local user_name="$1"
  local plist_path="$2"
  local user_uid
  user_uid="$(id -u "$user_name")"

  if [[ "$(id -u)" -eq 0 ]]; then
    launchctl bootout "gui/$user_uid" "$plist_path" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/$user_uid" "$plist_path" >/dev/null 2>&1 || true
    return
  fi

  launchctl unload "$plist_path" >/dev/null 2>&1 || true
  launchctl load "$plist_path" >/dev/null 2>&1 || true
}

TARGET_USER="$(resolve_target_user)"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  echo "Unable to determine target user; skip launch agent setup."
  exit 0
fi

USER_HOME="$(resolve_user_home "$TARGET_USER")"
USER_SUPPORT_DIR="$USER_HOME/Library/Application Support/CSUStudentWiFi"
LAUNCH_AGENTS_DIR="$USER_HOME/Library/LaunchAgents"
CONFIG_PATH="$USER_SUPPORT_DIR/config.toml"
STATE_PATH="$USER_SUPPORT_DIR/auto_relogin_state.json"
LOG_PATH="$USER_SUPPORT_DIR/auto_relogin.log"
PLIST_PATH="$LAUNCH_AGENTS_DIR/${LAUNCH_AGENT_LABEL}.plist"
BIN_PATH="$APP_SUPPORT_DIR/bin/csu-auto-relogin"

mkdir -p "$USER_SUPPORT_DIR" "$LAUNCH_AGENTS_DIR"

if [[ ! -f "$CONFIG_PATH" ]]; then
  cp "$APP_SUPPORT_DIR/config.example.toml" "$CONFIG_PATH"
fi

python3 - "$CONFIG_PATH" "$STATE_PATH" "$LOG_PATH" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
state_path = Path(sys.argv[2])
log_path = Path(sys.argv[3])
text = config_path.read_text(encoding="utf-8")
text = text.replace('state_file = "auto_relogin_state.json"', f'state_file = "{state_path}"')
text = text.replace('log_file = "auto_relogin.log"', f'log_file = "{log_path}"')
config_path.write_text(text, encoding="utf-8")
PY

cat >"$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${BIN_PATH}</string>
        <string>--config</string>
        <string>${CONFIG_PATH}</string>
        <string>--once</string>
    </array>
    <key>ProcessType</key>
    <string>Background</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>${START_INTERVAL_SECONDS}</integer>
</dict>
</plist>
EOF

if [[ "$(id -u)" -eq 0 ]]; then
  chown -R "$TARGET_USER":staff "$USER_SUPPORT_DIR" "$LAUNCH_AGENTS_DIR"
fi
chmod 600 "$CONFIG_PATH" "$PLIST_PATH"

if [[ "$LOAD_IF_READY" -eq 1 ]] && config_is_ready "$CONFIG_PATH"; then
  reload_launch_agent "$TARGET_USER" "$PLIST_PATH"
  echo "LaunchAgent is installed, loaded, and will start silently after login."
else
  echo "LaunchAgent is prepared at $PLIST_PATH."
  echo "Edit $CONFIG_PATH first, then run $APP_SUPPORT_DIR/setup_launch_agent.sh --load-if-ready"
fi
