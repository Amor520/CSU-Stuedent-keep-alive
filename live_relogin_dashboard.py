#!/usr/bin/env python3
"""Serve a live dashboard and start real verification runs from the page."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from render_relogin_report import classify, latest_run, parse_log_entries, state_timestamp, summarize


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #09101f;
      --panel: rgba(19, 27, 49, 0.94);
      --line: #2b3657;
      --text: #eef3ff;
      --muted: #a7b3d1;
      --success: #31c48d;
      --error: #ff6b6b;
      --step: #60a5fa;
      --wait: #f59e0b;
      --skip: #9ca3af;
      --noop: #8b5cf6;
      --info: #38bdf8;
      --button: #2dd4bf;
      --button-hover: #14b8a6;
      --button-disabled: #51607f;
    }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #09101f, #0f1730 35%, #09111f);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 18px 60px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
    }}
    .sub {{
      color: var(--muted);
      margin-bottom: 22px;
      line-height: 1.65;
    }}
    .status-row {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(15, 23, 48, 0.95);
      color: var(--text);
      font-weight: 600;
    }}
    .dot-live {{
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--wait);
      box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.12);
    }}
    .dot-done {{
      background: var(--success);
      box-shadow: 0 0 0 6px rgba(49, 196, 141, 0.12);
    }}
    .action-row {{
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }}
    .start-button {{
      appearance: none;
      border: none;
      border-radius: 14px;
      background: linear-gradient(135deg, var(--button), #38bdf8);
      color: #04101f;
      font-size: 16px;
      font-weight: 800;
      padding: 13px 18px;
      cursor: pointer;
      box-shadow: 0 14px 28px rgba(45, 212, 191, 0.2);
      transition: transform 0.15s ease, background 0.15s ease, opacity 0.15s ease;
    }}
    .start-button:hover:enabled {{
      transform: translateY(-1px);
      background: linear-gradient(135deg, var(--button-hover), #22c55e);
    }}
    .start-button:disabled {{
      cursor: not-allowed;
      background: var(--button-disabled);
      color: #dbe6ff;
      box-shadow: none;
      opacity: 0.85;
    }}
    .action-hint {{
      color: var(--muted);
      line-height: 1.6;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px 16px;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.18);
    }}
    .k {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .v {{
      font-size: 18px;
      font-weight: 700;
      line-height: 1.35;
      word-break: break-word;
    }}
    .success {{ color: var(--success); }}
    .error {{ color: var(--error); }}
    .info {{ color: var(--info); }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.18);
    }}
    .panel + .panel {{
      margin-top: 18px;
    }}
    .panel-title {{
      margin: 0 0 16px;
      font-size: 18px;
    }}
    .timeline-item {{
      position: relative;
      display: flex;
      gap: 14px;
      padding: 0 0 14px;
    }}
    .timeline-item:last-child {{
      padding-bottom: 0;
    }}
    .timeline-dot {{
      position: relative;
      width: 12px;
      min-width: 12px;
      height: 12px;
      margin-top: 7px;
      border-radius: 999px;
      background: var(--info);
      box-shadow: 0 0 0 6px rgba(56, 189, 248, 0.12);
    }}
    .timeline-item:not(:last-child) .timeline-dot::after {{
      content: "";
      position: absolute;
      left: 5px;
      top: 18px;
      width: 2px;
      height: calc(100% + 2px);
      background: var(--line);
    }}
    .timeline-item.success .timeline-dot {{ background: var(--success); box-shadow: 0 0 0 6px rgba(49, 196, 141, 0.12); }}
    .timeline-item.error .timeline-dot {{ background: var(--error); box-shadow: 0 0 0 6px rgba(255, 107, 107, 0.12); }}
    .timeline-item.step .timeline-dot {{ background: var(--step); box-shadow: 0 0 0 6px rgba(96, 165, 250, 0.12); }}
    .timeline-item.wait .timeline-dot {{ background: var(--wait); box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.12); }}
    .timeline-item.skip .timeline-dot {{ background: var(--skip); box-shadow: 0 0 0 6px rgba(156, 163, 175, 0.12); }}
    .timeline-item.noop .timeline-dot {{ background: var(--noop); box-shadow: 0 0 0 6px rgba(139, 92, 246, 0.12); }}
    .timeline-body {{
      flex: 1;
      min-width: 0;
    }}
    .timeline-meta {{
      display: flex;
      gap: 10px;
      align-items: center;
      margin-bottom: 6px;
      flex-wrap: wrap;
    }}
    .timeline-label {{
      font-weight: 700;
    }}
    .timeline-time {{
      color: var(--muted);
      font-size: 13px;
    }}
    .timeline-message {{
      line-height: 1.55;
      word-break: break-word;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      color: #dce7ff;
      line-height: 1.55;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      max-height: 340px;
      overflow: auto;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{title}</h1>
    <div class="sub">
      这个页面会实时刷新。你可以直接看脚本是否在后台“无感”完成解绑、等待、预热门户和重新登录。
    </div>

    <div class="status-row">
      <div class="pill"><span id="run-dot" class="dot-live"></span><span id="run-status">待开始</span></div>
      <div class="pill">自动刷新：1 秒</div>
      <div class="pill" id="server-time">--</div>
    </div>

    <div class="action-row">
      <button id="start-button" class="start-button">在线演示 开始测试</button>
      <div id="action-hint" class="action-hint">点击按钮后，会强制执行一次真实重登录演示。</div>
    </div>

    <div class="cards" id="cards"></div>

    <div class="panel">
      <h2 class="panel-title">实时时间线</h2>
      <div id="timeline"></div>
    </div>

    <div class="panel">
      <h2 class="panel-title">原始日志</h2>
      <pre id="raw-log">等待日志...</pre>
    </div>
  </div>

  <script>
    const cardsEl = document.getElementById("cards");
    const timelineEl = document.getElementById("timeline");
    const rawLogEl = document.getElementById("raw-log");
    const runStatusEl = document.getElementById("run-status");
    const runDotEl = document.getElementById("run-dot");
    const serverTimeEl = document.getElementById("server-time");
    const startButtonEl = document.getElementById("start-button");
    const actionHintEl = document.getElementById("action-hint");

    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }}

    function card(title, value, cls) {{
      return `<div class="card"><div class="k">${{escapeHtml(title)}}</div><div class="v ${{cls || ""}}">${{escapeHtml(value)}}</div></div>`;
    }}

    function renderCards(summary, status) {{
      const cards = [
        card("结果", summary.outcome, summary.outcome_class),
        card("模式", summary.run_mode, "info"),
        card("浏览器弹窗", summary.browser_popup, "info"),
        card("预计断网窗口", summary.portal_interrupt, "info"),
        card("状态文件时间戳", summary.state_value, "info"),
        card("运行状态", status.label, status.class_name),
        card("开始时间", summary.start_time, "info"),
        card("结束时间", summary.end_time, "info"),
      ];
      cardsEl.innerHTML = cards.join("");
    }}

    function renderTimeline(entries) {{
      if (!entries.length) {{
        timelineEl.innerHTML = '<div class="timeline-message">点击上面的按钮后，这里会实时展示时间线。</div>';
        return;
      }}
      timelineEl.innerHTML = entries.map((entry) => `
        <div class="timeline-item ${{entry.kind}}">
          <div class="timeline-dot"></div>
          <div class="timeline-body">
            <div class="timeline-meta">
              <span class="timeline-label">${{escapeHtml(entry.label)}}</span>
              <span class="timeline-time">${{escapeHtml(entry.time)}}</span>
            </div>
            <div class="timeline-message">${{escapeHtml(entry.message)}}</div>
          </div>
        </div>
      `).join("");
    }}

    async function startDemo() {{
      startButtonEl.disabled = true;
      actionHintEl.textContent = "正在请求开始测试...";
      try {{
        const response = await fetch("/api/start", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
        }});
        const payload = await response.json();
        actionHintEl.textContent = payload.message || "开始测试请求已发出。";
      }} catch (error) {{
        actionHintEl.textContent = `启动失败：${{error}}`;
      }}
      await refresh();
    }}

    async function refresh() {{
      try {{
        const response = await fetch("/api/status", {{ cache: "no-store" }});
        const payload = await response.json();
        renderCards(payload.summary, payload.run_status);
        renderTimeline(payload.entries);
        rawLogEl.textContent = payload.raw_log || "还没有运行日志";
        runStatusEl.textContent = payload.run_status.label;
        runDotEl.className = payload.run_status.finished ? "dot-live dot-done" : "dot-live";
        serverTimeEl.textContent = `服务时间：${{payload.server_time}}`;
        startButtonEl.textContent = payload.run_status.button_label;
        startButtonEl.disabled = !payload.run_status.can_start;
        actionHintEl.textContent = payload.run_status.message || "点击按钮后，会强制执行一次真实重登录演示。";
      }} catch (error) {{
        runStatusEl.textContent = "读取失败";
        rawLogEl.textContent = String(error);
        actionHintEl.textContent = "页面读取状态失败，请稍后重试。";
      }}
    }}

    startButtonEl.addEventListener("click", startDemo);
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
"""


class DemoRunner:
    def __init__(
        self,
        python_bin: Path,
        runner_script: Path,
        config_path: Path,
        workdir: Path,
        log_path: Path,
        status_path: Path,
    ) -> None:
        self.python_bin = python_bin
        self.runner_script = runner_script
        self.config_path = config_path
        self.workdir = workdir
        self.log_path = log_path
        self.status_path = status_path
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def reset_idle(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")
        self._write_status(
            "idle",
            exit_code=None,
            message="点击“在线演示 开始测试”后，会强制执行一次真实重登录演示。",
            started_at="",
            finished_at="",
        )

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._process and self._process.poll() is None:
                return False, "演示正在进行中，请等待当前这次结束。"
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.write_text("", encoding="utf-8")
            started_at = datetime_now_text()
            self._write_status(
                "starting",
                exit_code=None,
                message="已收到开始测试请求，马上启动真实演示。",
                started_at=started_at,
                finished_at="",
            )
            thread = threading.Thread(target=self._run, args=(started_at,), daemon=True)
            thread.start()
            return True, "开始测试请求已发出。"

    def _run(self, started_at: str) -> None:
        command = [
            str(self.python_bin),
            str(self.runner_script),
            "--config",
            str(self.config_path),
            "--once",
            "--verbose",
            "--force-relogin",
        ]
        self._write_status(
            "running",
            exit_code=None,
            message="正在执行真实重登录演示，请观察下面的时间线。",
            started_at=started_at,
            finished_at="",
        )

        exit_code = -1
        final_status = "failed"
        final_message = "演示启动失败"
        try:
            with self.log_path.open("w", encoding="utf-8", buffering=1) as fh:
                process = subprocess.Popen(
                    command,
                    cwd=self.workdir,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                with self._lock:
                    self._process = process
                exit_code = process.wait()
        except Exception as exc:  # pragma: no cover - defensive
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime_now_text()} [ERROR] Unable to start demo run: {exc}\n")
            final_message = f"演示启动失败：{exc}"
        else:
            if exit_code == 0:
                final_status = "finished"
                final_message = "演示已完成，可以查看最终结果。"
            else:
                final_message = f"演示失败，退出码 {exit_code}。"
        finally:
            with self._lock:
                self._process = None
            self._write_status(
                final_status,
                exit_code=exit_code,
                message=final_message,
                started_at=started_at,
                finished_at=datetime_now_text(),
            )

    def _load_status_payload(self) -> dict[str, Any]:
        if not self.status_path.exists():
            return {}
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _write_status(
        self,
        status: str,
        *,
        exit_code: int | None,
        message: str,
        started_at: str,
        finished_at: str,
    ) -> None:
        payload = self._load_status_payload()
        payload.update(
            {
                "status": status,
                "exit_code": exit_code,
                "message": message,
                "updated_at": datetime_now_text(),
                "started_at": started_at,
                "finished_at": finished_at,
            }
        )
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve a live dashboard for one verification run")
    parser.add_argument("--log", required=True, help="Path to the verification log")
    parser.add_argument("--state", default="", help="Optional path to auto_relogin_state.json")
    parser.add_argument("--status", required=True, help="Path to a JSON status file written by the runner")
    parser.add_argument("--python-bin", required=True, help="Python executable used to start the real run")
    parser.add_argument("--runner-script", required=True, help="Path to auto_relogin.py")
    parser.add_argument("--config", required=True, help="Path to config.toml")
    parser.add_argument("--workdir", required=True, help="Working directory for the real run")
    parser.add_argument("--title", default="CSU WiFi 无感重登录实时观测", help="Dashboard title")
    parser.add_argument("--port", type=int, default=8765, help="Local HTTP port")
    return parser.parse_args()


def load_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        payload: dict[str, Any] = {"status": "idle", "exit_code": None, "message": ""}
    else:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            payload = {"status": "unknown", "exit_code": None, "message": "状态读取失败"}

    status = str(payload.get("status") or "idle")
    mapping = {
        "idle": ("待开始", False, "info", True, "在线演示 开始测试"),
        "starting": ("准备中", False, "info", False, "测试启动中..."),
        "running": ("运行中", False, "info", False, "测试进行中..."),
        "finished": ("已完成", True, "success", True, "重新开始测试"),
        "failed": ("已失败", True, "error", True, "重新开始测试"),
    }
    label, finished, class_name, can_start, button_label = mapping.get(
        status, ("未知", False, "info", True, "在线演示 开始测试")
    )
    payload["label"] = label
    payload["finished"] = finished
    payload["class_name"] = class_name
    payload["can_start"] = can_start
    payload["button_label"] = button_label
    return payload


def build_payload(log_path: Path, state_path: Path | None, status_path: Path) -> dict[str, Any]:
    entries = latest_run(parse_log_entries(log_path)) if log_path.exists() else []
    run_status = load_status(status_path)
    state_value = state_timestamp(state_path)

    if entries:
        summary = summarize(entries, state_value)
    else:
        summary = {
            "outcome": run_status["label"],
            "outcome_class": run_status["class_name"],
            "run_mode": "在线演示",
            "browser_popup": "无",
            "portal_interrupt": "--",
            "state_value": state_value,
            "start_time": run_status.get("started_at") or "未开始",
            "end_time": run_status.get("finished_at") or "未结束",
            "line_count": 0,
        }

    if run_status.get("started_at"):
        summary["start_time"] = run_status["started_at"]
    if run_status.get("finished_at"):
        summary["end_time"] = run_status["finished_at"]
    if run_status["status"] in {"starting", "running"}:
        summary["outcome"] = "进行中"
        summary["outcome_class"] = "info"
        summary["run_mode"] = "在线演示"

    rendered_entries = []
    raw_lines = []
    for entry in entries:
        kind, label = classify(entry)
        rendered_entries.append(
            {
                "kind": kind,
                "label": label,
                "time": entry.timestamp.strftime("%H:%M:%S"),
                "message": entry.message,
            }
        )
        raw_lines.append(f"{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')} [{entry.level}] {entry.message}")

    return {
        "summary": summary,
        "entries": rendered_entries,
        "raw_log": "\n".join(raw_lines),
        "run_status": run_status,
        "server_time": datetime_now_text(),
    }


def datetime_now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def json_response(handler: BaseHTTPRequestHandler, status_code: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(
    log_path: Path,
    state_path: Path | None,
    status_path: Path,
    title: str,
    runner: DemoRunner,
):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/status":
                json_response(self, HTTPStatus.OK, build_payload(log_path, state_path, status_path))
                return

            if parsed.path == "/":
                body = HTML_TEMPLATE.format(title=title).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/start":
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return

            started, message = runner.start()
            payload = build_payload(log_path, state_path, status_path)
            payload["ok"] = started
            payload["message"] = message
            status_code = HTTPStatus.ACCEPTED if started else HTTPStatus.CONFLICT
            json_response(self, status_code, payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return Handler


def ensure_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            raise SystemExit(f"Port {port} is unavailable: {exc}") from exc


def main() -> int:
    args = parse_args()
    log_path = Path(args.log).expanduser()
    state_path = Path(args.state).expanduser() if args.state else None
    status_path = Path(args.status).expanduser()
    runner = DemoRunner(
        python_bin=Path(args.python_bin).expanduser(),
        runner_script=Path(args.runner_script).expanduser(),
        config_path=Path(args.config).expanduser(),
        workdir=Path(args.workdir).expanduser(),
        log_path=log_path,
        status_path=status_path,
    )
    runner.reset_idle()

    ensure_port(args.port)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(log_path, state_path, status_path, args.title, runner),
    )
    print(f"Live dashboard ready at http://127.0.0.1:{args.port}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
