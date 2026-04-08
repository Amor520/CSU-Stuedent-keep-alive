#!/usr/bin/env python3
"""Render a simple HTML timeline for the latest auto re-login run."""

from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(?P<ms>\d{3}) \[(?P<level>[A-Z]+)\] (?P<msg>.*)$"
)


@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a visual report for the latest re-login run")
    parser.add_argument("--log", required=True, help="Path to the run log or auto_relogin.log")
    parser.add_argument("--state", default="", help="Optional path to auto_relogin_state.json")
    parser.add_argument("--out", required=True, help="Output HTML path")
    parser.add_argument("--title", default="CSU WiFi 无感重登录验证", help="Report title")
    return parser.parse_args()


def parse_log_entries(path: Path) -> list[LogEntry]:
    entries: list[LogEntry] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LOG_LINE_RE.match(raw_line)
        if not match:
            continue
        timestamp = datetime.strptime(
            f"{match.group('ts')}.{match.group('ms')}",
            "%Y-%m-%d %H:%M:%S.%f",
        )
        entries.append(
            LogEntry(
                timestamp=timestamp,
                level=match.group("level"),
                message=match.group("msg"),
            )
        )
    return entries


def latest_run(entries: list[LogEntry], gap_seconds: int = 120) -> list[LogEntry]:
    if not entries:
        return []
    groups: list[list[LogEntry]] = [[entries[0]]]
    for entry in entries[1:]:
        prev = groups[-1][-1]
        if (entry.timestamp - prev.timestamp).total_seconds() > gap_seconds:
            groups.append([entry])
        else:
            groups[-1].append(entry)
    return groups[-1]


def classify(entry: LogEntry) -> tuple[str, str]:
    message = entry.message.lower()
    if "portal login success" in message:
        return "success", "登录成功"
    if "portal login rejected" in message or "portal request failed" in message:
        return "error", "登录失败"
    if "portal mac unbind success" in message:
        return "success", "解绑成功"
    if "portal mac unbind rejected" in message or "mac unbind request failed" in message:
        return "error", "解绑失败"
    if "attempting mac unbind" in message:
        return "step", "发起解绑"
    if "attempting portal login" in message:
        return "step", "发起登录"
    if "waiting " in message and "portal session to settle" in message:
        return "wait", "冷却等待"
    if "portal warmup request" in message:
        return "warmup", "预热门户"
    if "skipping portal actions" in message:
        return "skip", "已跳过"
    if "network already online; nothing to do" in message:
        return "noop", "无需动作"
    return "info", "日志"


def state_timestamp(path: Path | None) -> str:
    if not path or not path.exists():
        return "未写入"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return "读取失败"
    return str(payload.get("last_successful_login") or "未写入")


def summarize(entries: list[LogEntry], state_value: str) -> dict[str, Any]:
    messages = [entry.message for entry in entries]
    joined = "\n".join(messages).lower()

    outcome = "成功"
    outcome_class = "success"
    if "portal login rejected" in joined or "portal request failed" in joined:
        outcome = "失败"
        outcome_class = "error"
    elif "skipping portal actions" in joined:
        outcome = "已跳过"
        outcome_class = "skip"
    elif "network already online; nothing to do" in joined:
        outcome = "无需动作"
        outcome_class = "noop"

    interruption_text = "无可见中断"
    interruption_seconds = None
    start = next(
        (
            entry.timestamp
            for entry in entries
            if "attempting mac unbind" in entry.message.lower()
            or "attempting portal login" in entry.message.lower()
        ),
        None,
    )
    end = next(
        (
            entry.timestamp
            for entry in reversed(entries)
            if "portal login success" in entry.message.lower()
            or "portal login rejected" in entry.message.lower()
            or "network already online; nothing to do" in entry.message.lower()
            or "skipping portal actions" in entry.message.lower()
        ),
        None,
    )
    if start and end:
        interruption_seconds = max(0.0, (end - start).total_seconds())
        interruption_text = f"约 {interruption_seconds:.1f} 秒"

    run_mode = "真实重登录"
    if "skipping portal actions" in joined:
        run_mode = "网络守卫跳过"
    elif "network already online; nothing to do" in joined:
        run_mode = "在线巡检"
    elif "attempting mac unbind" not in joined and "attempting portal login" in joined:
        run_mode = "直接登录"

    return {
        "outcome": outcome,
        "outcome_class": outcome_class,
        "run_mode": run_mode,
        "browser_popup": "无",
        "portal_interrupt": interruption_text,
        "state_value": state_value,
        "start_time": entries[0].timestamp.strftime("%Y-%m-%d %H:%M:%S") if entries else "无",
        "end_time": entries[-1].timestamp.strftime("%Y-%m-%d %H:%M:%S") if entries else "无",
        "line_count": len(entries),
    }


def render_html(title: str, entries: list[LogEntry], summary: dict[str, Any]) -> str:
    cards = [
        ("结果", summary["outcome"], summary["outcome_class"]),
        ("模式", summary["run_mode"], "info"),
        ("浏览器弹窗", summary["browser_popup"], "info"),
        ("预计断网窗口", summary["portal_interrupt"], "info"),
        ("状态文件时间戳", summary["state_value"], "info"),
        ("开始时间", summary["start_time"], "info"),
    ]
    timeline_parts: list[str] = []
    raw_parts: list[str] = []
    for entry in entries:
        kind, label = classify(entry)
        timestamp = entry.timestamp.strftime("%H:%M:%S")
        timeline_parts.append(
            f"""
            <div class="item {kind}">
              <div class="dot"></div>
              <div class="content">
                <div class="meta">
                  <span class="label">{html.escape(label)}</span>
                  <span class="time">{html.escape(timestamp)}</span>
                </div>
                <div class="message">{html.escape(entry.message)}</div>
              </div>
            </div>
            """
        )
        raw_parts.append(f"{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')} [{entry.level}] {entry.message}")

    card_html = "".join(
        f'<div class="card {css}"><div class="k">{html.escape(key)}</div><div class="v">{html.escape(value)}</div></div>'
        for key, value, css in cards
    )
    raw_text = html.escape("\n".join(raw_parts) or "没有日志")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0b1020;
      --panel: #131b31;
      --panel2: #0f1730;
      --text: #eef3ff;
      --muted: #a7b3d1;
      --line: #2b3657;
      --success: #31c48d;
      --error: #ff6b6b;
      --step: #60a5fa;
      --wait: #f59e0b;
      --skip: #9ca3af;
      --noop: #8b5cf6;
      --info: #38bdf8;
    }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #09101f, #0f1730 35%, #0a1120);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1040px;
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
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 22px;
    }}
    .card {{
      background: rgba(19, 27, 49, 0.92);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px 16px;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.18);
    }}
    .card .k {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .card .v {{
      font-size: 18px;
      font-weight: 700;
      line-height: 1.35;
      word-break: break-word;
    }}
    .card.success .v {{ color: var(--success); }}
    .card.error .v {{ color: var(--error); }}
    .timeline, .raw {{
      background: rgba(19, 27, 49, 0.92);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.18);
    }}
    .section-title {{
      margin: 0 0 16px;
      font-size: 18px;
    }}
    .timeline {{
      margin-bottom: 18px;
    }}
    .item {{
      position: relative;
      display: flex;
      gap: 14px;
      padding: 0 0 14px;
    }}
    .item:last-child {{
      padding-bottom: 0;
    }}
    .dot {{
      position: relative;
      width: 12px;
      min-width: 12px;
      height: 12px;
      margin-top: 7px;
      border-radius: 999px;
      background: var(--info);
      box-shadow: 0 0 0 6px rgba(56, 189, 248, 0.12);
    }}
    .item:not(:last-child) .dot::after {{
      content: "";
      position: absolute;
      left: 5px;
      top: 18px;
      width: 2px;
      height: calc(100% + 2px);
      background: var(--line);
    }}
    .item.success .dot {{ background: var(--success); box-shadow: 0 0 0 6px rgba(49, 196, 141, 0.12); }}
    .item.error .dot {{ background: var(--error); box-shadow: 0 0 0 6px rgba(255, 107, 107, 0.12); }}
    .item.step .dot {{ background: var(--step); box-shadow: 0 0 0 6px rgba(96, 165, 250, 0.12); }}
    .item.wait .dot {{ background: var(--wait); box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.12); }}
    .item.skip .dot {{ background: var(--skip); box-shadow: 0 0 0 6px rgba(156, 163, 175, 0.12); }}
    .item.noop .dot {{ background: var(--noop); box-shadow: 0 0 0 6px rgba(139, 92, 246, 0.12); }}
    .content {{
      flex: 1;
      min-width: 0;
    }}
    .meta {{
      display: flex;
      gap: 10px;
      align-items: center;
      margin-bottom: 6px;
      flex-wrap: wrap;
    }}
    .label {{
      font-weight: 700;
    }}
    .time {{
      color: var(--muted);
      font-size: 13px;
    }}
    .message {{
      color: var(--text);
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
    }}
    .tip {{
      margin: 18px 0 22px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(15, 23, 48, 0.9);
      border: 1px solid var(--line);
      color: var(--muted);
      line-height: 1.6;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{html.escape(title)}</h1>
    <div class="sub">这个页面用于验证脚本是否真正做到了“无感后台重登录”。浏览器不会被脚本自动打开；你主要看时间线和结果卡片。</div>

    <div class="cards">{card_html}</div>

    <div class="tip">
      你现在看到的是脚本最近一次运行的可视化结果。若结果为“成功”，就表示它已经在后台完成了
      “网络守卫判断 → 解绑/下线 → 等待冷却 → 预热 portal → 重新登录 → 写入时间戳”。
    </div>

    <div class="timeline">
      <h2 class="section-title">时间线</h2>
      {''.join(timeline_parts) if timeline_parts else '<div class="message">没有找到可展示的日志。</div>'}
    </div>

    <div class="raw">
      <h2 class="section-title">原始日志</h2>
      <pre>{raw_text}</pre>
    </div>
  </div>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    log_path = Path(args.log).expanduser()
    out_path = Path(args.out).expanduser()
    state_path = Path(args.state).expanduser() if args.state else None

    entries = latest_run(parse_log_entries(log_path))
    summary = summarize(entries, state_timestamp(state_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(args.title, entries, summary), encoding="utf-8")
    print(f"Report written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
