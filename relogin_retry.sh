#!/bin/zsh

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_PATH="${1:-$SCRIPT_DIR/config.toml}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-48}"
SLEEP_ON_SKIP="${SLEEP_ON_SKIP:-30}"
SLEEP_ON_FAIL="${SLEEP_ON_FAIL:-15}"

if [ ! -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  echo "Missing virtualenv at $SCRIPT_DIR/.venv"
  exit 1
fi

cd "$SCRIPT_DIR" || exit 1
source "$SCRIPT_DIR/.venv/bin/activate"

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "[$(date '+%F %T')] relogin attempt $attempt/$MAX_ATTEMPTS"
  python auto_relogin.py --config "$CONFIG_PATH" --once --verbose
  exit_code=$?

  if [ "$exit_code" -eq 0 ]; then
    echo "[$(date '+%F %T')] relogin flow finished successfully"
    exit 0
  fi

  if [ "$exit_code" -eq 3 ]; then
    echo "[$(date '+%F %T')] waiting for target Wi-Fi SSID"
    sleep "$SLEEP_ON_SKIP"
  else
    echo "[$(date '+%F %T')] portal login failed, retrying soon"
    sleep "$SLEEP_ON_FAIL"
  fi

  attempt=$((attempt + 1))
done

echo "[$(date '+%F %T')] retries exhausted"
exit 1
