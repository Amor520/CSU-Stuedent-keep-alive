#!/usr/bin/env python3
"""Local visual setup wizard for the CSU auto re-login tool."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import threading
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

APP_SUPPORT_DIR = Path("/Library/Application Support/CSUStudentWiFi")
USER_SUPPORT_DIR = Path.home() / "Library/Application Support/CSUStudentWiFi"
LAUNCH_AGENT_PATH = Path.home() / "Library/LaunchAgents/cn.csu.autorelogin.plist"
CONFIG_PATH = USER_SUPPORT_DIR / "config.toml"
STATE_PATH = USER_SUPPORT_DIR / "auto_relogin_state.json"
LOG_PATH = USER_SUPPORT_DIR / "auto_relogin.log"
SETUP_SCRIPT = APP_SUPPORT_DIR / "setup_launch_agent.sh"
DISABLE_SCRIPT = APP_SUPPORT_DIR / "disable_launch_agent.sh"
RUNNER_BIN = APP_SUPPORT_DIR / "bin/csu-auto-relogin"
EXAMPLE_CONFIG_PATH = APP_SUPPORT_DIR / "config.example.toml"

HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7fb;
      --bg-hero: linear-gradient(180deg, #eef4ff 0%, #f8fbff 45%, #f5f7fb 100%);
      --panel: #ffffff;
      --panel-soft: #f8fafc;
      --line: #e3e8f2;
      --line-strong: #d7deea;
      --text: #162033;
      --muted: #6b778d;
      --accent: #2563eb;
      --accent-2: #60a5fa;
      --accent-soft: #eef4ff;
      --ok: #16a34a;
      --ok-soft: #ecfdf3;
      --warn: #d97706;
      --warn-soft: #fff7ed;
      --bad: #dc2626;
      --bad-soft: #fef2f2;
      --chip: #eff5ff;
      --shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg-hero);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.3fr 0.9fr;
      gap: 18px;
      margin-bottom: 20px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 22px;
      box-shadow: var(--shadow);
    }}
    .title {{
      font-size: 34px;
      font-weight: 800;
      letter-spacing: -0.02em;
      margin: 0 0 12px;
    }}
    .sub {{
      color: var(--muted);
      line-height: 1.8;
      margin: 0;
      font-size: 15px;
    }}
    .steps {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 20px;
    }}
    .chip {{
      padding: 9px 13px;
      border-radius: 999px;
      background: var(--chip);
      border: 1px solid #dce6fb;
      color: var(--accent);
      font-weight: 700;
      font-size: 13px;
    }}
    .hero-note {{
      margin-top: 18px;
      padding: 14px 16px;
      border-radius: 18px;
      background: var(--panel-soft);
      border: 1px solid var(--line);
      color: var(--muted);
      line-height: 1.7;
      font-size: 14px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .card {{
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px 16px;
    }}
    .k {{
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .v {{
      font-size: 17px;
      font-weight: 700;
      line-height: 1.45;
      word-break: break-word;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
      gap: 20px;
      align-items: start;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 23px;
      letter-spacing: -0.01em;
    }}
    .section-sub {{
      margin: -4px 0 18px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.7;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .simple-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .field {{
      display: flex;
      flex-direction: column;
      gap: 9px;
    }}
    .field.full {{
      grid-column: 1 / -1;
    }}
    label {{
      font-size: 13px;
      font-weight: 700;
      color: var(--text);
    }}
    input, textarea, select {{
      width: 100%;
      border-radius: 16px;
      border: 1px solid var(--line-strong);
      background: #ffffff;
      color: var(--text);
      padding: 13px 14px;
      font-size: 15px;
      outline: none;
      box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.02);
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }}
    input:focus, textarea:focus, select:focus {{
      border-color: #9ec1ff;
      box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12);
    }}
    input[readonly], textarea[readonly] {{
      background: #f8fafc;
    }}
    textarea {{
      min-height: 110px;
      resize: vertical;
      line-height: 1.7;
    }}
    .hint {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    details {{
      margin-top: 18px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fafcff;
      padding: 14px 16px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--text);
      user-select: none;
    }}
    .advanced-body {{
      margin-top: 16px;
    }}
    .action-help {{
      margin-top: 16px;
      padding: 12px 14px;
      border-radius: 16px;
      background: var(--accent-soft);
      border: 1px solid #dce6fb;
      color: #35527e;
      font-size: 14px;
      line-height: 1.7;
    }}
    .actions {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}
    button {{
      appearance: none;
      border: 1px solid transparent;
      border-radius: 16px;
      padding: 13px 18px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 800;
      transition: transform 0.14s ease, opacity 0.14s ease, box-shadow 0.14s ease;
    }}
    button:hover {{
      transform: translateY(-1px);
      box-shadow: 0 10px 18px rgba(37, 99, 235, 0.12);
    }}
    button.primary {{
      background: linear-gradient(135deg, #2563eb, #3b82f6);
      color: #ffffff;
    }}
    button.secondary {{
      background: #ffffff;
      color: #28456f;
      border-color: #d8e3f8;
    }}
    button.warn {{
      background: #ffffff;
      color: #9a3412;
      border-color: #fed7aa;
    }}
    .status {{
      margin-top: 16px;
      border-radius: 16px;
      padding: 14px 16px;
      background: var(--ok-soft);
      border: 1px solid #cdeed8;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .status.warn {{
      background: var(--warn-soft);
      border-color: #f6d7ae;
    }}
    .status.bad {{
      background: var(--bad-soft);
      border-color: #fecaca;
    }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }}
    .log {{
      margin-top: 16px;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      min-height: 220px;
      max-height: 420px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.55;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      color: #24324a;
    }}
    .muted {{
      color: var(--muted);
    }}
    @media (max-width: 860px) {{
      .hero, .layout {{
        grid-template-columns: 1fr;
      }}
      .grid, .simple-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="panel">
        <div class="title">{title}</div>
        <p class="sub">
          这是一个更轻松的设置页。你只需要填账号和密码，
          保存之后就能启用开机自动运行，并在页面里直接完成一次真实测试。
        </p>
        <div class="steps">
          <div class="chip">步骤 1：填写账号</div>
          <div class="chip">步骤 2：保存配置</div>
          <div class="chip">步骤 3：启用自动运行</div>
          <div class="chip">步骤 4：立即测试</div>
        </div>
        <div class="hero-note">
          默认按中国移动处理，不用再手动输入运营商后缀、AC IP、AC 名称。
          只有你以后想微调高级行为时，再展开高级选项即可。
        </div>
      </div>
      <div class="panel">
        <h2>当前概览</h2>
        <div class="section-sub">这里会实时告诉你：配置是否完成、自动运行是否开启，以及最近一次测试结果。</div>
        <div class="cards" id="cards"></div>
      </div>
    </div>

    <div class="layout">
      <div class="panel">
        <h2>基础设置</h2>
        <div class="section-sub">按你的目标，默认只需要填账号和密码。其他内容都已经替你收起来了。</div>
        <div class="simple-grid">
          <div class="field">
            <label for="username">校园网账号</label>
            <input id="username" placeholder="例如 8208231325">
          </div>
          <div class="field">
            <label>默认运营商</label>
            <input value="中国移动（默认 @cmccn）" readonly>
            <div class="hint">默认按中国移动处理；如果以后想改联通/电信，在下方“高级选项”里再改。</div>
          </div>
          <div class="field full">
            <label for="password">校园网密码</label>
            <input id="password" type="password" placeholder="输入真实密码">
          </div>
        </div>

        <details>
          <summary>高级选项（通常不用填）</summary>
          <div class="advanced-body">
            <div class="grid">
              <div class="field">
                <label for="account_suffix">运营商后缀</label>
                <input id="account_suffix" list="suffixes" placeholder="@cmccn">
                <datalist id="suffixes">
                  <option value="@cmccn"></option>
                  <option value="@unicomn"></option>
                  <option value="@telecomn"></option>
                  <option value="@zndx"></option>
                </datalist>
              </div>
              <div class="field">
                <label for="required_ssid">限定 Wi-Fi 名称（可选）</label>
                <input id="required_ssid" placeholder="留空则主要按校园网 IP 判断">
              </div>
              <div class="field">
                <label for="ac_ip">AC IP（可选）</label>
                <input id="ac_ip" placeholder="现在默认不用填">
              </div>
              <div class="field">
                <label for="ac_name">AC 名称（可选）</label>
                <input id="ac_name" placeholder="现在默认不用填">
              </div>
              <div class="field">
                <label for="campus_ipv4_cidrs">校园网 IPv4 段</label>
                <input id="campus_ipv4_cidrs" placeholder="100.64.0.0/10">
              </div>
              <div class="field">
                <label for="force_relogin_hours">第几小时主动重登</label>
                <input id="force_relogin_hours" type="number" min="1" step="1">
              </div>
              <div class="field">
                <label for="relogin_cooldown_seconds">解绑后等待秒数</label>
                <input id="relogin_cooldown_seconds" type="number" min="0" step="1">
              </div>
              <div class="field">
                <label for="interface">网卡名（可选）</label>
                <input id="interface" placeholder="例如 en0">
              </div>
              <div class="field full">
                <label for="mac_override">MAC 覆盖值</label>
                <input id="mac_override" placeholder="默认 000000000000">
              </div>
            </div>
          </div>
        </details>

        <div class="grid">
          <div class="field">
            <label for="notes">使用说明</label>
            <textarea id="notes" readonly>推荐顺序：先保存配置，再启用自动运行，最后点“立即测试一次”。

“立即测试一次”现在会直接强制执行一次真实重新登录，不再看本地时间戳。
如果测试时你本来就在线，脚本会先解绑再重新登录，所以可能会有几秒短暂断网，这是正常现象。

页面会持续刷新状态，但不会再覆盖你正在输入的内容。</textarea>
          </div>
        </div>
        <div class="action-help">推荐顺序：先点“保存配置”，再点“启用自动运行”，最后点“立即测试一次”。这里的“立即测试一次”会强制重新登录，不会参考本地时间戳。</div>
        <div class="actions">
          <button id="save-button" class="primary">1. 保存配置</button>
          <button id="enable-button" class="secondary">2. 启用自动运行</button>
          <button id="test-button" class="primary">3. 立即测试一次</button>
          <button id="disable-button" class="warn">停用自动运行</button>
        </div>
        <div id="page-status" class="status">正在读取当前状态…</div>
      </div>

      <div class="panel">
        <h2>测试与日志</h2>
        <div class="hint">
          这里会显示“立即测试一次”的实时结果，以及最近日志片段。测试成功后，你能直接看到解绑、等待、预热和重新登录的全过程。
        </div>
        <div id="test-status" class="status warn">还没有开始测试。</div>
        <div id="test-log" class="log">等待操作…</div>
      </div>
    </div>
  </div>

  <script>
    const setupToken = {token_json};
    let formInitialized = false;

    function byId(id) {{
      return document.getElementById(id);
    }}

    function textOrDash(value) {{
      if (value === null || value === undefined || value === "") return "未设置";
      return String(value);
    }}

    function describeExitCode(test) {{
      if (test.running) return "测试进行中";
      if (test.last_exit_code === null || test.last_exit_code === undefined) return "还没测试";
      if (test.last_exit_code === 0) return "测试成功";
      if (test.last_exit_code === 3) return "已跳过";
      return `失败（exit=${{test.last_exit_code}}）`;
    }}

    function describeLastTest(test) {{
      if (test.running) {{
        return `正在测试（开始于 ${{test.started_at || "刚刚"}}）`;
      }}
      if (test.last_exit_code === null || test.last_exit_code === undefined) {{
        return "你还没有执行过测试";
      }}
      if (test.last_exit_code === 0) {{
        return `最近一次测试成功${{test.finished_at ? "，完成于 " + test.finished_at : ""}}`;
      }}
      if (test.last_exit_code === 3) {{
        return `最近一次测试被跳过${{test.finished_at ? "，完成于 " + test.finished_at : ""}}`;
      }}
      return `最近一次测试失败（exit=${{test.last_exit_code}}）${{test.finished_at ? "，完成于 " + test.finished_at : ""}}`;
    }}

    function populateForm(cfg) {{
      byId("username").value = cfg.username || "";
      byId("password").value = cfg.password || "";
      byId("account_suffix").value = cfg.account_suffix || "@cmccn";
      byId("ac_ip").value = cfg.ac_ip || "";
      byId("ac_name").value = cfg.ac_name || "";
      byId("required_ssid").value = cfg.required_ssid || "";
      byId("campus_ipv4_cidrs").value = (cfg.campus_ipv4_cidrs || []).join(", ");
      byId("force_relogin_hours").value = cfg.force_relogin_hours ?? "";
      byId("relogin_cooldown_seconds").value = cfg.relogin_cooldown_seconds ?? "";
      byId("interface").value = cfg.interface || "";
      byId("mac_override").value = cfg.mac_override || "";
    }}

    function currentPayload() {{
      return {{
        username: byId("username").value.trim(),
        password: byId("password").value,
        account_suffix: byId("account_suffix").value.trim(),
        ac_ip: byId("ac_ip").value.trim(),
        ac_name: byId("ac_name").value.trim(),
        required_ssid: byId("required_ssid").value.trim(),
        campus_ipv4_cidrs: byId("campus_ipv4_cidrs").value.trim(),
        force_relogin_hours: byId("force_relogin_hours").value.trim(),
        relogin_cooldown_seconds: byId("relogin_cooldown_seconds").value.trim(),
        interface: byId("interface").value.trim(),
        mac_override: byId("mac_override").value.trim(),
      }};
    }}

    async function api(path, options = {{}}) {{
      const headers = Object.assign({{}}, options.headers || {{}}, {{
        "X-Setup-Token": setupToken,
      }});
      const response = await fetch(path, Object.assign({{}}, options, {{ headers }}));
      const data = await response.json();
      if (!response.ok) {{
        throw new Error(data.error || "请求失败");
      }}
      return data;
    }}

    function applyState(data) {{
      const cfg = data.config;
      if (!formInitialized) {{
        populateForm(cfg);
        formInitialized = true;
      }}

      const cards = [
        ["配置文件", data.config_path],
        ["状态文件", data.state_path],
        ["日志文件", data.log_path],
        ["开机自动运行", data.autostart_loaded ? "已经开启" : "还没开启"],
        ["配置状态", data.config_ready ? "已经可用" : "还没填完整"],
        ["最近测试", describeExitCode(data.test)],
      ];
      byId("cards").innerHTML = cards.map(([k, v]) => `
        <div class="card">
          <div class="k">${{k}}</div>
          <div class="v">${{textOrDash(v)}}</div>
        </div>
      `).join("");

      byId("page-status").className = `status ${{data.config_ready ? "" : "warn"}}`.trim();
      byId("page-status").textContent =
        `配置文件：${{data.config_path}}\n` +
        `自动运行：${{data.autostart_loaded ? "已开启" : "未开启"}}\n` +
        `最近测试：${{describeLastTest(data.test)}}\n` +
        `当前建议：${{data.config_ready ? "可以直接启用自动运行，或者先再点一次测试确认。" : "先把账号和密码填好，然后点“保存配置”。"}}`;

      renderTest(data.test, data.log_tail);
    }}

    function renderTest(test, logTail) {{
      let statusText = "还没有开始测试。";
      let statusClass = "status warn";
      if (test.running) {{
        statusText = `测试中：${{test.started_at || "刚刚开始"}}`;
        statusClass = "status";
      }} else if (test.last_exit_code !== null) {{
        statusText = describeLastTest(test);
        statusClass = test.last_exit_code === 0 ? "status" : (test.last_exit_code === 3 ? "status warn" : "status bad");
      }}
      byId("test-status").className = statusClass;
      byId("test-status").textContent = statusText;

      const chunks = [];
      if (test.output) {{
        chunks.push("[本次测试输出]\\n" + test.output.trim());
      }}
      if (logTail) {{
        chunks.push("[最近日志]\\n" + logTail.trim());
      }}
      byId("test-log").textContent = chunks.length ? chunks.join("\\n\\n") : "等待操作…";
    }}

    async function refresh() {{
      try {{
        const data = await api("/api/state");
        applyState(data);
      }} catch (error) {{
        byId("page-status").className = "status bad";
        byId("page-status").textContent = `读取状态失败：${{error.message}}`;
      }}
    }}

    async function saveConfig() {{
      try {{
        const data = await api("/api/save", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(currentPayload()),
        }});
        formInitialized = false;
        byId("page-status").className = "status";
        byId("page-status").textContent = data.message;
        await refresh();
      }} catch (error) {{
        byId("page-status").className = "status bad";
        byId("page-status").textContent = `保存失败：${{error.message}}`;
      }}
    }}

    async function simpleAction(path, okPrefix) {{
      try {{
        const data = await api(path, {{ method: "POST" }});
        byId("page-status").className = "status";
        byId("page-status").textContent = `${{okPrefix}}\\n\\n${{data.message}}`;
        await refresh();
      }} catch (error) {{
        byId("page-status").className = "status bad";
        byId("page-status").textContent = `${{okPrefix}}失败：${{error.message}}`;
      }}
    }}

    byId("save-button").addEventListener("click", saveConfig);
    byId("enable-button").addEventListener("click", () => simpleAction("/api/enable", "自动运行已处理"));
    byId("disable-button").addEventListener("click", () => simpleAction("/api/disable", "自动运行已停用"));
    byId("test-button").addEventListener("click", () => simpleAction("/api/test", "测试任务已发起"));

    refresh();
    setInterval(refresh, 1500);
  </script>
</body>
</html>
"""


def json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler, text: str) -> None:
    body = text.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if tomllib is None:
        raise RuntimeError("The setup wizard requires tomllib support.")
    with path.open("rb") as fh:
        return tomllib.load(fh)


def ensure_user_config() -> None:
    USER_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        return
    source = EXAMPLE_CONFIG_PATH if EXAMPLE_CONFIG_PATH.exists() else Path(__file__).with_name("config.example.toml")
    text = source.read_text(encoding="utf-8")
    text = text.replace('state_file = "auto_relogin_state.json"', f'state_file = "{STATE_PATH}"')
    text = text.replace('log_file = "auto_relogin.log"', f'log_file = "{LOG_PATH}"')
    CONFIG_PATH.write_text(text, encoding="utf-8")
    os.chmod(CONFIG_PATH, 0o600)


def default_config() -> dict[str, Any]:
    ensure_user_config()
    raw = load_toml(CONFIG_PATH)
    return normalize_config(raw)


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    creds = raw.get("credentials", {})
    network = raw.get("network", {})
    client = raw.get("client", {})
    return {
        "username": creds.get("username", ""),
        "password": creds.get("password", ""),
        "account_suffix": creds.get("account_suffix", "@cmccn"),
        "ac_ip": network.get("ac_ip", ""),
        "ac_name": network.get("ac_name", ""),
        "required_ssid": client.get("required_ssid", ""),
        "campus_ipv4_cidrs": client.get("campus_ipv4_cidrs", ["100.64.0.0/10"]),
        "force_relogin_hours": client.get("force_relogin_hours", 144),
        "relogin_cooldown_seconds": client.get("relogin_cooldown_seconds", 6),
        "interface": client.get("interface", ""),
        "mac_override": client.get("mac_override", "000000000000"),
    }


def config_ready(config: dict[str, Any]) -> bool:
    required = (
        config.get("username", "").strip(),
        config.get("password", "").strip(),
    )
    if not all(required):
        return False
    if config["username"] == "20211234567":
        return False
    if config["password"] == "replace-with-real-password":
        return False
    return True


def parse_cidrs(text: str) -> list[str]:
    items = [part.strip() for part in text.replace("\n", ",").split(",")]
    return [item for item in items if item]


def render_config(config: dict[str, Any]) -> str:
    cidr_list = config["campus_ipv4_cidrs"] or ["100.64.0.0/10"]
    cidr_toml = ", ".join(json.dumps(item, ensure_ascii=True) for item in cidr_list)
    return (
        "[credentials]\n"
        f'username = {json.dumps(config["username"], ensure_ascii=True)}\n'
        f'password = {json.dumps(config["password"], ensure_ascii=True)}\n'
        f'account_suffix = {json.dumps(config["account_suffix"], ensure_ascii=True)}\n'
        "\n"
        "[network]\n"
        'portal_host = "portal.csu.edu.cn"\n'
        "portal_port = 802\n"
        "login_method = 1\n"
        'callback = "dr1004"\n'
        f'ac_ip = {json.dumps(config["ac_ip"], ensure_ascii=True)}\n'
        f'ac_name = {json.dumps(config["ac_name"], ensure_ascii=True)}\n'
        "terminal_type = 1\n"
        'check_url = "http://connectivitycheck.gstatic.com/generate_204"\n'
        'fallback_check_url = "http://www.baidu.com"\n'
        "verify_certificate = true\n"
        "prefer_mac_unbind = true\n"
        'unbind_callback = "dr1002"\n'
        'logout_user_account = "drcom"\n'
        'logout_user_password = "123"\n'
        "logout_ac_logout = 1\n"
        "logout_register_mode = 1\n"
        'logout_user_ipv6 = ""\n'
        "logout_vlan_id = 0\n"
        "\n"
        "[client]\n"
        "check_interval_seconds = 45\n"
        f'force_relogin_hours = {int(config["force_relogin_hours"])}\n'
        f'relogin_cooldown_seconds = {int(config["relogin_cooldown_seconds"])}\n'
        "max_backoff_seconds = 300\n"
        f'log_file = {json.dumps(str(LOG_PATH), ensure_ascii=True)}\n'
        f'state_file = {json.dumps(str(STATE_PATH), ensure_ascii=True)}\n'
        f'interface = {json.dumps(config["interface"], ensure_ascii=True)}\n'
        f'mac_override = {json.dumps(config["mac_override"], ensure_ascii=True)}\n'
        f'required_ssid = {json.dumps(config["required_ssid"], ensure_ascii=True)}\n'
        f"campus_ipv4_cidrs = [{cidr_toml}]\n"
    )


def tail_text(path: Path, limit: int = 80) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-limit:])


def launchctl_loaded() -> bool:
    proc = subprocess.run(
        ["launchctl", "list"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return "cn.csu.autorelogin" in proc.stdout


class TestRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running = False
        self.output = ""
        self.started_at = ""
        self.finished_at = ""
        self.last_exit_code: int | None = None

    def summary(self) -> dict[str, Any]:
        with self._lock:
            exit_summary = None
            if self.last_exit_code is not None:
                exit_summary = f"exit={self.last_exit_code}"
            return {
                "running": self.running,
                "output": self.output,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "last_exit_code": self.last_exit_code,
                "last_exit_summary": exit_summary,
            }

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self.running:
                return False, "已有测试在运行中，请稍等。"
            self.running = True
            self.output = ""
            self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.finished_at = ""
            self.last_exit_code = None
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        return True, "已开始执行一次真实测试。"

    def _run(self) -> None:
        command = [str(RUNNER_BIN), "--config", str(CONFIG_PATH), "--once", "--force-relogin", "--verbose"]
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        with self._lock:
            self.running = False
            self.output = proc.stdout.strip()
            self.last_exit_code = proc.returncode
            self.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SetupState:
    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(24)
        self.tester = TestRunner()

    def read_state(self) -> dict[str, Any]:
        config = default_config()
        return {
            "config": config,
            "config_ready": config_ready(config),
            "config_path": str(CONFIG_PATH),
            "state_path": str(STATE_PATH),
            "log_path": str(LOG_PATH),
            "autostart_loaded": launchctl_loaded(),
            "test": self.tester.summary(),
            "log_tail": tail_text(LOG_PATH),
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = default_config()
        account_suffix = str(payload.get("account_suffix", "")).strip() or config.get("account_suffix") or "@cmccn"
        config.update(
            {
                "username": str(payload.get("username", "")).strip(),
                "password": str(payload.get("password", "")),
                "account_suffix": account_suffix,
                "ac_ip": str(payload.get("ac_ip", "")).strip(),
                "ac_name": str(payload.get("ac_name", "")).strip(),
                "required_ssid": str(payload.get("required_ssid", "")).strip(),
                "campus_ipv4_cidrs": parse_cidrs(str(payload.get("campus_ipv4_cidrs", ""))),
                "interface": str(payload.get("interface", "")).strip(),
                "mac_override": str(payload.get("mac_override", "")).strip() or "000000000000",
            }
        )
        force_hours = str(payload.get("force_relogin_hours", "")).strip() or str(config["force_relogin_hours"])
        cooldown = str(payload.get("relogin_cooldown_seconds", "")).strip() or str(config["relogin_cooldown_seconds"])
        config["force_relogin_hours"] = max(1, int(force_hours))
        config["relogin_cooldown_seconds"] = max(0, int(cooldown))
        if not config["campus_ipv4_cidrs"]:
            config["campus_ipv4_cidrs"] = ["100.64.0.0/10"]
        CONFIG_PATH.write_text(render_config(config), encoding="utf-8")
        os.chmod(CONFIG_PATH, 0o600)
        return {
            "message": (
                "配置已保存到："
                f"\n{CONFIG_PATH}\n\n"
                "默认中国移动后缀会自动保留。\n"
                "下一步直接点“启用自动运行”，或者先点“立即测试一次”。"
            )
        }

    def run_script(self, path: Path, *args: str) -> dict[str, Any]:
        proc = subprocess.run(
            [str(path), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stdout.strip() or f"{path.name} failed")
        return {"message": proc.stdout.strip() or "完成"}


class WizardHandler(BaseHTTPRequestHandler):
    server_version = "CSUSetupWizard/1.0"

    @property
    def state(self) -> SetupState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _require_token(self) -> bool:
        if self.command == "GET":
            return True
        token = self.headers.get("X-Setup-Token", "")
        if token == self.state.token:
            return True
        json_response(self, {"error": "token invalid"}, status=403)
        return False

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            html = HTML_TEMPLATE.format(
                title="CSU Wi-Fi 可视化设置页",
                token_json=json.dumps(self.state.token),
            )
            html_response(self, html)
            return
        if path == "/api/state":
            json_response(self, self.state.read_state())
            return
        json_response(self, {"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if not self._require_token():
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/save":
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                json_response(self, self.state.save(payload))
                return
            if path == "/api/enable":
                json_response(self, self.state.run_script(SETUP_SCRIPT, "--load-if-ready"))
                return
            if path == "/api/disable":
                json_response(self, self.state.run_script(DISABLE_SCRIPT))
                return
            if path == "/api/test":
                config = default_config()
                if not config_ready(config):
                    raise RuntimeError("配置还不完整，请先填好账号、密码、后缀、AC IP、AC 名称并保存。")
                started, message = self.state.tester.start()
                if not started:
                    raise RuntimeError(message)
                json_response(self, {"message": message})
                return
            json_response(self, {"error": "not found"}, status=404)
        except Exception as exc:  # pragma: no cover - defensive
            json_response(self, {"error": str(exc)}, status=400)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CSU visual setup wizard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_user_config()
    server = ThreadingHTTPServer((args.host, args.port), WizardHandler)
    server.state = SetupState()  # type: ignore[attr-defined]
    host, port = server.server_address
    url = f"http://{host}:{port}/"
    print(f"CSU Wi-Fi setup wizard is running at {url}")
    print("Keep this process alive while you use the page. Press Ctrl+C to stop it.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSetup wizard stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
