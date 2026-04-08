#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPORT_DIR="$ROOT_DIR/reports"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
RUN_LOG="$REPORT_DIR/live-verify-$RUN_ID.log"
RUN_STATUS="$REPORT_DIR/live-verify-$RUN_ID.status.json"
SERVER_LOG="$REPORT_DIR/live-verify-$RUN_ID.server.log"

mkdir -p "$REPORT_DIR"
: > "$RUN_LOG"
cat > "$RUN_STATUS" <<EOF
{"status":"idle","exit_code":null,"message":"点击页面按钮开始真实在线演示。","started_at":"","finished_at":""}
EOF

PORT="$("$ROOT_DIR/.venv/bin/python" - <<'PY'
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
)"

"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/live_relogin_dashboard.py" \
  --log "$RUN_LOG" \
  --state "$ROOT_DIR/auto_relogin_state.json" \
  --status "$RUN_STATUS" \
  --python-bin "$ROOT_DIR/.venv/bin/python" \
  --runner-script "$ROOT_DIR/auto_relogin.py" \
  --config "$ROOT_DIR/config.toml" \
  --workdir "$ROOT_DIR" \
  --title "CSU WiFi 无感重登录实时观测" \
  --port "$PORT" \
  > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

sleep 1

URL="http://127.0.0.1:$PORT/"
echo "实时观测页面已启动：$URL"
echo "浏览器会自动打开。现在请直接点击页面里的“在线演示 开始测试”按钮。"
echo "关闭当前终端或按 Ctrl+C，即可结束这次实时观测服务。"
echo

open "$URL" >/dev/null 2>&1 || true

wait "$SERVER_PID" || true
