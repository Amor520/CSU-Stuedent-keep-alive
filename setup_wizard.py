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
      color-scheme: light dark;
      --bg: #08101f;
      --panel: rgba(14, 21, 40, 0.96);
      --panel-soft: rgba(20, 29, 53, 0.92);
      --line: #2a3558;
      --text: #eef4ff;
      --muted: #9eb0d3;
      --accent: #4fd1c5;
      --accent-2: #60a5fa;
      --ok: #31c48d;
      --warn: #f59e0b;
      --bad: #f87171;
      --chip: rgba(79, 209, 197, 0.12);
      --shadow: 0 18px 42px rgba(0, 0, 0, 0.28);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: linear-gradient(180deg, #08101f, #0e1830 38%, #09101d);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .wrap {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 18px 54px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.3fr 0.9fr;
      gap: 16px;
      margin-bottom: 18px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: var(--shadow);
    }}
    .title {{
      font-size: 30px;
      font-weight: 800;
      margin: 0 0 10px;
    }}
    .sub {{
      color: var(--muted);
      line-height: 1.7;
      margin: 0;
    }}
    .steps {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}
    .chip {{
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--chip);
      border: 1px solid rgba(79, 209, 197, 0.18);
      color: #dffcf6;
      font-weight: 700;
      font-size: 13px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 14px;
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
      margin-bottom: 6px;
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
      gap: 18px;
      align-items: start;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 20px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .field {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .field.full {{
      grid-column: 1 / -1;
    }}
    label {{
      font-size: 13px;
      font-weight: 700;
      color: #dbe8ff;
    }}
    input, textarea, select {{
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(8, 13, 26, 0.84);
      color: var(--text);
      padding: 12px 13px;
      font-size: 14px;
      outline: none;
    }}
    textarea {{
      min-height: 84px;
      resize: vertical;
      line-height: 1.5;
    }}
    .hint {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}
    button {{
      appearance: none;
      border: none;
      border-radius: 14px;
      padding: 12px 16px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 800;
      transition: transform 0.14s ease, opacity 0.14s ease;
    }}
    button:hover {{
      transform: translateY(-1px);
    }}
    button.primary {{
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      color: #07101c;
    }}
    button.secondary {{
      background: rgba(96, 165, 250, 0.18);
      color: #ddecff;
      border: 1px solid rgba(96, 165, 250, 0.26);
    }}
    button.warn {{
      background: rgba(245, 158, 11, 0.18);
      color: #ffe9bf;
      border: 1px solid rgba(245, 158, 11, 0.28);
    }}
    .status {{
      margin-top: 16px;
      border-radius: 16px;
      padding: 12px 14px;
      background: rgba(79, 209, 197, 0.08);
      border: 1px solid rgba(79, 209, 197, 0.18);
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .status.warn {{
      background: rgba(245, 158, 11, 0.08);
      border-color: rgba(245, 158, 11, 0.22);
    }}
    .status.bad {{
      background: rgba(248, 113, 113, 0.08);
      border-color: rgba(248, 113, 113, 0.22);
    }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }}
    .log {{
      margin-top: 16px;
      background: rgba(7, 12, 24, 0.95);
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
      color: #e1ebff;
    }}
    .muted {{
      color: var(--muted);
    }}
    @media (max-width: 860px) {{
      .hero, .layout {{
        grid-template-columns: 1fr;
      }}
      .grid {{
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
          把原来的 3 步命令行流程变成一个可视化向导：
          先填配置，再点按钮保存并开启自动运行，最后直接在页面里跑一次真实测试。
        </p>
        <div class="steps">
          <div class="chip">1. 填写账号配置</div>
          <div class="chip">2. 保存到本机</div>
          <div class="chip">3. 开启开机自启</div>
          <div class="chip">4. 立即测试</div>
        </div>
      </div>
      <div class="panel">
        <h2>当前状态</h2>
        <div class="cards" id="cards"></div>
      </div>
    </div>

    <div class="layout">
      <div class="panel">
        <h2>设置页面</h2>
        <div class="grid">
          <div class="field">
            <label for="username">校园网账号</label>
            <input id="username" placeholder="例如 8208231325">
          </div>
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
          <div class="field full">
            <label for="password">校园网密码</label>
            <input id="password" type="password" placeholder="输入真实密码">
          </div>
          <div class="field">
            <label for="ac_ip">AC IP</label>
            <input id="ac_ip" placeholder="抓包得到的 wlan_ac_ip">
          </div>
          <div class="field">
            <label for="ac_name">AC 名称</label>
            <input id="ac_name" placeholder="抓包得到的 wlan_ac_name">
          </div>
          <div class="field">
            <label for="required_ssid">限定 Wi-Fi 名称（可选）</label>
            <input id="required_ssid" placeholder="留空则主要按校园网 IP 判断">
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
          <div class="field">
            <label for="mac_override">MAC 覆盖值</label>
            <input id="mac_override" placeholder="默认 000000000000">
          </div>
          <div class="field full">
            <label for="notes">说明</label>
            <textarea id="notes" readonly>首次保存后，页面不会直接联网。你需要再点“启用自动运行”或“立即测试”。
“立即测试”会执行一次真实重登录：如果当前在线，可能会有几秒瞬时断网，这是正常现象。</textarea>
          </div>
        </div>
        <div class="actions">
          <button id="save-button" class="primary">保存配置</button>
          <button id="enable-button" class="secondary">启用自动运行</button>
          <button id="test-button" class="primary">立即测试一次</button>
          <button id="disable-button" class="warn">停用自动运行</button>
        </div>
        <div id="page-status" class="status">正在读取当前状态…</div>
      </div>

      <div class="panel">
        <h2>测试输出</h2>
        <div class="hint">
          这里会显示“立即测试一次”的实时结果，以及最近日志片段。
        </div>
        <div id="test-status" class="status warn">还没有开始测试。</div>
        <div id="test-log" class="log">等待操作…</div>
      </div>
    </div>
  </div>

  <script>
    const setupToken = {token_json};

    function byId(id) {{
      return document.getElementById(id);
    }}

    function textOrDash(value) {{
      if (value === null || value === undefined || value === "") return "未设置";
      return String(value);
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
      byId("username").value = cfg.username || "";
      byId("password").value = cfg.password || "";
      byId("account_suffix").value = cfg.account_suffix || "";
      byId("ac_ip").value = cfg.ac_ip || "";
      byId("ac_name").value = cfg.ac_name || "";
      byId("required_ssid").value = cfg.required_ssid || "";
      byId("campus_ipv4_cidrs").value = (cfg.campus_ipv4_cidrs || []).join(", ");
      byId("force_relogin_hours").value = cfg.force_relogin_hours ?? "";
      byId("relogin_cooldown_seconds").value = cfg.relogin_cooldown_seconds ?? "";
      byId("interface").value = cfg.interface || "";
      byId("mac_override").value = cfg.mac_override || "";

      const cards = [
        ["配置文件", data.config_path],
        ["状态文件", data.state_path],
        ["日志文件", data.log_path],
        ["自动运行", data.autostart_loaded ? "已启用" : "未启用"],
        ["配置是否完整", data.config_ready ? "看起来已可用" : "还缺少关键字段"],
        ["最近测试", data.test.running ? "测试中" : textOrDash(data.test.last_exit_summary)],
      ];
      byId("cards").innerHTML = cards.map(([k, v]) => `
        <div class="card">
          <div class="k">${{k}}</div>
          <div class="v">${{textOrDash(v)}}</div>
        </div>
      `).join("");

      byId("page-status").className = `status ${data.config_ready ? "" : "warn"}`.trim();
      byId("page-status").textContent =
        `配置文件：${{data.config_path}}\n` +
        `自动运行：${{data.autostart_loaded ? "已加载" : "未加载"}}\n` +
        `当前建议：${{data.config_ready ? "可以直接启用自动运行或立即测试。" : "先把账号、密码、后缀、AC IP、AC 名称填完整再保存。"}}`;

      renderTest(data.test, data.log_tail);
    }}

    function renderTest(test, logTail) {{
      let statusText = "还没有开始测试。";
      let statusClass = "status warn";
      if (test.running) {{
        statusText = `测试中：${{test.started_at || "刚刚开始"}}`;
        statusClass = "status";
      }} else if (test.last_exit_code !== null) {{
        statusText = `最近测试结束：exit=${{test.last_exit_code}}${{test.finished_at ? "，完成时间 " + test.finished_at : ""}}`;
        statusClass = test.last_exit_code === 0 ? "status" : "status bad";
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
        config.get("account_suffix", "").strip(),
        config.get("ac_ip", "").strip(),
        config.get("ac_name", "").strip(),
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
        command = [str(RUNNER_BIN), "--config", str(CONFIG_PATH), "--once", "--verbose"]
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
        config.update(
            {
                "username": str(payload.get("username", "")).strip(),
                "password": str(payload.get("password", "")),
                "account_suffix": str(payload.get("account_suffix", "")).strip(),
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
