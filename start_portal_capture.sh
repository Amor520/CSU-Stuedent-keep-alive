#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CAPTURE_ROOT="$ROOT_DIR/captures"
RUNTIME_DIR="$ROOT_DIR/.capture_runtime"
SESSION_ID="$(date +%Y%m%d-%H%M%S)"
SESSION_DIR="$CAPTURE_ROOT/$SESSION_ID"
PROFILE_DIR="$RUNTIME_DIR/chrome-profile-live"
LOG_FILE="$SESSION_DIR/requests.jsonl"
NODE_LOG="$SESSION_DIR/capture.log"
REMOTE_DEBUG_PORT="${REMOTE_DEBUG_PORT:-9222}"
TARGET_URL="${TARGET_URL:-https://portal.csu.edu.cn/}"
TARGET_HINT="${TARGET_HINT:-portal.csu.edu.cn}"
mkdir -p "$SESSION_DIR" "$PROFILE_DIR" "$RUNTIME_DIR"
echo "$SESSION_DIR" > "$RUNTIME_DIR/latest_session"
printf 'target_url=%s\ntarget_hint=%s\nremote_debug_port=%s\n' \
  "$TARGET_URL" "$TARGET_HINT" "$REMOTE_DEBUG_PORT" > "$SESSION_DIR/session.env"

pkill -f "$PROFILE_DIR" 2>/dev/null || true
pkill -f "capture_chrome_requests.mjs --port $REMOTE_DEBUG_PORT" 2>/dev/null || true

nohup node "$ROOT_DIR/capture_chrome_requests.mjs" \
  --port "$REMOTE_DEBUG_PORT" \
  --out "$LOG_FILE" \
  --target-hint "$TARGET_HINT" \
  --max-idle-seconds 1800 \
  > "$NODE_LOG" 2>&1 &
echo $! > "$SESSION_DIR/capture.pid"

open -na "Google Chrome" --args \
  --remote-debugging-port="$REMOTE_DEBUG_PORT" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  --new-window \
  "$TARGET_URL" \
  >/dev/null 2>&1

sleep 2
pgrep -f "$PROFILE_DIR" | head -n 1 > "$SESSION_DIR/chrome.pid" || true

echo "Capture session: $SESSION_DIR"
echo "Chrome will open a dedicated portal window."
echo "Default target is: $TARGET_URL"
echo "Please complete the manual portal action there, then close that dedicated Chrome window."
