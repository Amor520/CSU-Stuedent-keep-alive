#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPORT_DIR="$ROOT_DIR/reports"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
RUN_LOG="$REPORT_DIR/verify-$RUN_ID.log"
RUN_HTML="$REPORT_DIR/verify-$RUN_ID.html"
LATEST_HTML="$REPORT_DIR/latest.html"

mkdir -p "$REPORT_DIR"

echo "Running one real verification..."
echo "This may briefly re-login the current campus network session."
echo

set +e
"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/auto_relogin.py" --config "$ROOT_DIR/config.toml" --once --verbose 2>&1 | tee "$RUN_LOG"
rc=${pipestatus[1]}
set -e

"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/render_relogin_report.py" \
  --log "$RUN_LOG" \
  --state "$ROOT_DIR/auto_relogin_state.json" \
  --out "$RUN_HTML"

cp "$RUN_HTML" "$LATEST_HTML"
open "$RUN_HTML" >/dev/null 2>&1 || true

echo
echo "Exit code: $rc"
echo "Run log: $RUN_LOG"
echo "HTML report: $RUN_HTML"

exit "$rc"
