#!/usr/bin/env python3
"""Lightweight CSU portal auto re-login helper.

The script periodically检测联网状态，必要时自动向 portal.csu.edu.cn 发送登录请求。
配置示例见 config.example.toml。
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import random
import re
import socket
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Type, TypeVar

try:  # Python >=3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older解释器
    import tomli as tomllib

import requests

CAPTIVE_HINTS = (b"portal.csu.edu.cn", b"eportal", b"wlan_user_ip")
DEFAULT_JS_VERSION = "4.1.3"
DEFAULT_LANG = "zh"
DEFAULT_V_PARAM_RANGE = (1000, 9999)
DEFAULT_LOGOUT_ACCOUNT = "drcom"
DEFAULT_LOGOUT_PASSWORD = "123"
DEFAULT_UNBIND_CALLBACK = "dr1002"
DEFAULT_RELOGIN_COOLDOWN_SECONDS = 6
DEFAULT_CAMPUS_IPV4_CIDRS = ("100.64.0.0/10",)
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
EPOCH = datetime.fromtimestamp(0)
EXIT_OK = 0
EXIT_FAILURE = 2
EXIT_SKIPPED = 3
SENSITIVE_LOG_KEYS = (
    "password",
    "user_password",
    "upass",
    "old_password",
    "new_password",
    "user_old_password",
    "user_new_password",
)
JSONP_WRAPPER_RE = re.compile(r"^[A-Za-z0-9_$.]+\((.*)\)$", flags=re.S)
T = TypeVar("T")


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Scrub secrets even if verbose HTTP logs are enabled.
        record.msg = redact_text_secrets(record.getMessage())
        record.args = ()
        return True


@dataclass
class Credentials:
    username: str
    password: str
    account_suffix: str


@dataclass
class NetworkProfile:
    portal_host: str
    portal_port: int
    login_method: int
    callback: str
    ac_ip: str
    ac_name: str
    terminal_type: int
    check_url: str
    fallback_check_url: str
    verify_certificate: bool
    prefer_mac_unbind: bool = True
    unbind_callback: str = DEFAULT_UNBIND_CALLBACK
    logout_user_account: str = DEFAULT_LOGOUT_ACCOUNT
    logout_user_password: str = DEFAULT_LOGOUT_PASSWORD
    logout_ac_logout: int = 1
    logout_register_mode: int = 1
    logout_user_ipv6: str = ""
    logout_vlan_id: int = 0


@dataclass
class ClientProfile:
    check_interval_seconds: int
    force_relogin_hours: int
    max_backoff_seconds: int
    log_file: str
    state_file: str
    interface: str
    mac_override: str
    required_ssid: str = ""
    relogin_cooldown_seconds: int = DEFAULT_RELOGIN_COOLDOWN_SECONDS
    campus_ipv4_cidrs: list[str] = field(default_factory=lambda: list(DEFAULT_CAMPUS_IPV4_CIDRS))


class PortalAutoLogin:
    def __init__(
        self,
        creds: Credentials,
        net: NetworkProfile,
        client: ClientProfile,
        config_dir: Path,
    ) -> None:
        self.creds = creds
        self.net = net
        self.client = client
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_BROWSER_USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        self.state_file = resolve_path(config_dir, client.state_file)
        self.last_successful_login = load_login_state(self.state_file)
        self._last_portal_warmup = 0.0
        self.force_relogin_requested = False

    # ------------------------- connectivity helpers -------------------------
    def is_online(self) -> bool:
        for idx, url in enumerate((self.net.check_url, self.net.fallback_check_url)):
            if not url:
                continue
            try:
                resp = self.session.get(
                    url,
                    timeout=4,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                logging.debug("Connectivity probe to %s failed: %s", url, exc)
                continue

            if resp.status_code == 204:
                return True
            if resp.status_code == 200 and idx == 1 and not looks_like_portal(resp):
                return True
        return False

    def need_forced_relogin(self) -> bool:
        margin = timedelta(hours=self.client.force_relogin_hours)
        return datetime.now() - self.last_successful_login >= margin

    def portal_root_url(self) -> str:
        return f"https://{self.net.portal_host}/"

    def portal_login_page_url(self) -> str:
        return f"https://{self.net.portal_host}/a79.htm"

    def portal_headers(self, referer: str = "") -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        return headers

    def warmup_portal(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_portal_warmup < 5:
            return

        root_url = self.portal_root_url()
        targets = (
            (root_url, root_url),
            (self.portal_login_page_url(), root_url),
        )
        for url, referer in targets:
            try:
                resp = self.session.get(
                    url,
                    timeout=6,
                    verify=self.net.verify_certificate,
                    allow_redirects=True,
                    headers=self.portal_headers(referer),
                )
            except requests.RequestException as exc:
                logging.debug("Portal warmup request to %s failed: %s", url, exc)
            else:
                logging.debug("Portal warmup request to %s -> HTTP %s", url, resp.status_code)

        self._last_portal_warmup = time.monotonic()

    def prepare_relogin_after_refresh(self) -> None:
        wait_seconds = max(0, self.client.relogin_cooldown_seconds)
        if wait_seconds:
            logging.info("Waiting %s seconds for portal session to settle", wait_seconds)
            time.sleep(wait_seconds)
        self.warmup_portal(force=True)

    def current_network_matches_guard(self) -> bool:
        current_ssid = get_current_wifi_ssid(self.client.interface)
        local_ip = detect_local_ip_safely(self.client.interface)
        cidrs = self.client.campus_ipv4_cidrs
        cidr_text = ", ".join(cidrs) if cidrs else "(none)"

        if self.client.required_ssid and current_ssid == self.client.required_ssid:
            return True

        if local_ip and ip_matches_any_cidr(local_ip, cidrs):
            if self.client.required_ssid and current_ssid and current_ssid != self.client.required_ssid:
                logging.info(
                    "Current Wi-Fi SSID is %s, but local IP %s matches campus ranges %s; proceeding",
                    current_ssid,
                    local_ip,
                    cidr_text,
                )
            elif self.client.required_ssid and not current_ssid:
                logging.info(
                    "Unable to confirm Wi-Fi SSID, but local IP %s matches campus ranges %s; proceeding",
                    local_ip,
                    cidr_text,
                )
            return True

        if self.client.required_ssid and current_ssid:
            logging.info(
                "Current Wi-Fi SSID is %s and local IP %s is outside campus ranges %s; skipping portal actions",
                current_ssid,
                local_ip or "unknown",
                cidr_text,
            )
            return False

        if self.client.required_ssid and not current_ssid:
            logging.info(
                "Unable to confirm Wi-Fi SSID and local IP %s is outside campus ranges %s; skipping portal actions",
                local_ip or "unknown",
                cidr_text,
            )
            return False

        logging.info(
            "Local IP %s is outside campus ranges %s; skipping portal actions",
            local_ip or "unknown",
            cidr_text,
        )
        return False

    # ------------------------------ login logic -----------------------------
    def login(self) -> bool:
        local_ip = detect_local_ip(self.client.interface)
        mac = self.client.mac_override or detect_mac(self.client.interface)
        self.warmup_portal()
        params = self._build_params(local_ip, mac)

        url = f"https://{self.net.portal_host}:{self.net.portal_port}/eportal/portal/login"
        logging.info(
            "Attempting portal login from %s with account %s",
            local_ip,
            mask_account(self.creds.username, self.creds.account_suffix),
        )
        try:
            resp = self.session.get(
                url,
                params=params,
                timeout=8,
                verify=self.net.verify_certificate,
                headers=self.portal_headers(self.portal_root_url()),
            )
        except requests.RequestException as exc:
            logging.error("Portal request failed: %s", exc)
            return False

        payload = parse_portal_response(resp.text, self.net.callback)
        if payload.get("result") in ("1", 1) and str(payload.get("ret_code", "0")) == "0":
            self.record_successful_login()
            logging.info("Portal login success: %s", payload.get("msg", ""))
            return True

        logging.warning(
            "Portal login rejected: ret_code=%s msg=%s", payload.get("ret_code"), payload.get("msg")
        )
        return False

    def logout(self) -> bool:
        local_ip = detect_local_ip(self.client.interface)
        mac = self.client.mac_override or detect_mac(self.client.interface)
        if self.net.prefer_mac_unbind and self.mac_unbind(local_ip, mac):
            return True
        return self.portal_logout(local_ip, mac)

    def _build_params(self, ip: str, mac: str) -> Dict[str, Any]:
        v_random = random.randint(*DEFAULT_V_PARAM_RANGE)
        user_account = f",0,{self.creds.username}{self.creds.account_suffix}"
        return {
            "callback": self.net.callback,
            "login_method": self.net.login_method,
            "user_account": user_account,
            "user_password": self.creds.password,
            "wlan_user_ip": ip,
            "wlan_user_ipv6": "",
            "wlan_user_mac": mac.replace(":", "").lower(),
            "wlan_ac_ip": self.net.ac_ip,
            "wlan_ac_name": self.net.ac_name,
            "jsVersion": DEFAULT_JS_VERSION,
            "terminal_type": self.net.terminal_type,
            "lang": DEFAULT_LANG,
            "v": v_random,
        }

    def _build_unbind_params(self, ip: str, mac: str) -> Dict[str, Any]:
        v_random = random.randint(*DEFAULT_V_PARAM_RANGE)
        return {
            "callback": self.net.unbind_callback,
            "user_account": self.creds.username,
            "wlan_user_mac": mac.replace(":", "").upper(),
            "wlan_user_ip": ipv4_to_portal_int(ip),
            "jsVersion": DEFAULT_JS_VERSION,
            "lang": DEFAULT_LANG,
            "v": v_random,
        }

    def _build_logout_params(self, ip: str, mac: str) -> Dict[str, Any]:
        v_random = random.randint(*DEFAULT_V_PARAM_RANGE)
        return {
            "callback": self.net.callback,
            "login_method": self.net.login_method,
            "user_account": self.net.logout_user_account,
            "user_password": self.net.logout_user_password,
            "ac_logout": self.net.logout_ac_logout,
            "register_mode": self.net.logout_register_mode,
            "wlan_user_ip": ip,
            "wlan_user_ipv6": self.net.logout_user_ipv6,
            "wlan_vlan_id": self.net.logout_vlan_id,
            "wlan_user_mac": mac.replace(":", "").lower(),
            "wlan_ac_ip": self.net.ac_ip,
            "wlan_ac_name": self.net.ac_name,
            "jsVersion": DEFAULT_JS_VERSION,
            "lang": DEFAULT_LANG,
            "v": v_random,
        }

    def mac_unbind(self, local_ip: str, mac: str) -> bool:
        params = self._build_unbind_params(local_ip, mac)
        url = f"https://{self.net.portal_host}:{self.net.portal_port}/eportal/portal/mac/unbind"
        logging.info("Session is due for refresh; attempting MAC unbind for %s", local_ip)
        try:
            resp = self.session.get(
                url,
                params=params,
                timeout=8,
                verify=self.net.verify_certificate,
                headers=self.portal_headers(self.portal_root_url()),
            )
        except requests.RequestException as exc:
            logging.warning("Portal MAC unbind request failed: %s", exc)
            return False

        payload = parse_portal_response(resp.text, self.net.unbind_callback)
        msg = payload.get("msg") or payload.get("message") or payload.get("raw") or "unknown response"
        success = payload.get("result") in ("1", 1, "ok")
        if success:
            logging.info("Portal MAC unbind success: %s", msg)
            return True
        logging.warning("Portal MAC unbind rejected: %s", msg)
        return False

    def portal_logout(self, local_ip: str, mac: str) -> bool:
        params = self._build_logout_params(local_ip, mac)
        url = f"https://{self.net.portal_host}:{self.net.portal_port}/eportal/portal/logout"
        logging.info("Falling back to portal logout for %s", local_ip)
        try:
            resp = self.session.get(
                url,
                params=params,
                timeout=8,
                verify=self.net.verify_certificate,
                headers=self.portal_headers(self.portal_root_url()),
            )
        except requests.RequestException as exc:
            logging.warning("Portal logout request failed: %s", exc)
            return False

        payload = parse_portal_response(resp.text, self.net.callback)
        msg = payload.get("msg") or payload.get("message") or payload.get("raw") or "unknown response"
        logging.info("Portal logout response: %s", msg)
        return True

    # ------------------------------ main loops ------------------------------
    def run_once(self) -> int:
        if not self.current_network_matches_guard():
            return EXIT_SKIPPED

        is_online = self.is_online()
        if self.force_relogin_requested or self.need_forced_relogin():
            if is_online:
                self.logout()
                self.prepare_relogin_after_refresh()
            success = self.login()
            return EXIT_OK if success else EXIT_FAILURE

        if is_online:
            logging.info("Network already online; nothing to do")
            return EXIT_OK

        success = self.login()
        return EXIT_OK if success else EXIT_FAILURE

    def run_forever(self) -> None:
        while True:
            exit_code = self.run_once()
            if exit_code in (EXIT_OK, EXIT_SKIPPED):
                sleep_time = self.client.check_interval_seconds
            else:
                sleep_time = min(self.client.max_backoff_seconds, self.client.check_interval_seconds * 2)
            jitter = random.uniform(0, 0.25 * self.client.check_interval_seconds)
            time.sleep(max(5, sleep_time + jitter))

    def record_successful_login(self) -> None:
        self.last_successful_login = datetime.now()
        save_login_state(self.state_file, self.last_successful_login)


# -------------------------------- utilities ---------------------------------

def looks_like_portal(resp: requests.Response) -> bool:
    content = resp.content[:512].lower()
    return any(hint in content for hint in CAPTIVE_HINTS)


def detect_local_ip(interface: str = "", target: str = "223.5.5.5", port: int = 80) -> str:
    if interface:
        ip_address = read_ipv4_from_ifconfig(interface)
        if ip_address:
            return ip_address

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target, port))
        return sock.getsockname()[0]
    finally:
        sock.close()


def detect_local_ip_safely(interface: str = "") -> str:
    try:
        return detect_local_ip(interface)
    except OSError as exc:
        logging.debug("Unable to determine local IPv4 address: %s", exc)
        return ""


def detect_mac(interface: str = "") -> str:
    if interface:
        mac = read_mac_from_ifconfig(interface)
        if mac:
            return mac
    mac_int = uuid.getnode()
    mac = "{:012x}".format(mac_int)
    return mac


def read_mac_from_ifconfig(interface: str) -> str:
    import subprocess

    commands = [
        ["/sbin/ifconfig", interface],
        ["ifconfig", interface],
    ]
    for cmd in commands:
        try:
            output = subprocess.check_output(cmd, text=True)
        except (OSError, subprocess.CalledProcessError):
            continue
        for line in output.splitlines():
            line = line.strip()
            if "ether" in line or "HWaddr" in line:
                parts = line.replace("\t", " ").split()
                for token in parts:
                    if token.count(":") == 5:
                        return token.replace(":", "")
        # macOS ifconfig en0 line: "ether aa:bb:..."
        if "ether" in output:
            marker = output.split("ether")[-1].split()[0]
            if marker.count(":") == 5:
                return marker.replace(":", "")
    return ""


def read_ipv4_from_ifconfig(interface: str) -> str:
    import subprocess

    commands = [
        ["/sbin/ifconfig", interface],
        ["ifconfig", interface],
    ]
    for cmd in commands:
        try:
            output = subprocess.check_output(cmd, text=True)
        except (OSError, subprocess.CalledProcessError):
            continue
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "127.0.0.1" not in line:
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
    return ""


def ipv4_to_portal_int(ip: str) -> str:
    parts = ip.strip().split(".")
    if len(parts) != 4:
        return ip
    try:
        value = 0
        for part in parts:
            octet = int(part)
            if octet < 0 or octet > 255:
                return ip
            value = (value << 8) | octet
    except ValueError:
        return ip
    return str(value)


def ip_matches_any_cidr(ip: str, cidrs: list[str]) -> bool:
    if not ip or not cidrs:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4:
        return False
    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        if network.version == 4 and addr in network:
            return True
    return False


def get_current_wifi_ssid(interface: str = "") -> str:
    if sys.platform != "darwin":
        return ""

    wifi_interface = interface or detect_wifi_interface()
    if wifi_interface:
        ssid = read_ssid_from_networksetup(wifi_interface)
        if ssid:
            return ssid

        ssid = read_ssid_from_system_profiler()
        if ssid:
            return ssid

        ssid = read_ssid_from_ipconfig(wifi_interface)
        if ssid:
            return ssid

    return read_ssid_from_airport()


def detect_wifi_interface() -> str:
    import subprocess

    commands = [
        ["/usr/sbin/networksetup", "-listallhardwareports"],
        ["networksetup", "-listallhardwareports"],
    ]
    for cmd in commands:
        try:
            output = subprocess.check_output(cmd, text=True)
        except (OSError, subprocess.CalledProcessError):
            continue
        lines = [line.strip() for line in output.splitlines()]
        for idx, line in enumerate(lines):
            if line == "Hardware Port: Wi-Fi" and idx + 1 < len(lines):
                next_line = lines[idx + 1]
                if next_line.startswith("Device: "):
                    return next_line.split(": ", 1)[1].strip()
    return ""


def read_ssid_from_networksetup(interface: str) -> str:
    import subprocess

    commands = [
        ["/usr/sbin/networksetup", "-getairportnetwork", interface],
        ["networksetup", "-getairportnetwork", interface],
    ]
    for cmd in commands:
        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        except (OSError, subprocess.CalledProcessError):
            continue
        line = output.strip()
        if ": " in line:
            return line.split(": ", 1)[1].strip()
    return ""


def read_ssid_from_ipconfig(interface: str) -> str:
    import subprocess

    commands = [
        ["ipconfig", "getsummary", interface],
        ["/usr/sbin/ipconfig", "getsummary", interface],
    ]
    for cmd in commands:
        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        except (OSError, subprocess.CalledProcessError):
            continue
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line.startswith("SSID : "):
                return line.split(" : ", 1)[1].strip()
    return ""


def read_ssid_from_system_profiler() -> str:
    import subprocess

    commands = [
        ["system_profiler", "SPAirPortDataType"],
    ]
    for cmd in commands:
        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        except (OSError, subprocess.CalledProcessError):
            continue
        lines = output.splitlines()
        for idx, raw_line in enumerate(lines):
            line = raw_line.rstrip()
            if line.strip() == "Current Network Information:":
                for follow_line in lines[idx + 1 :]:
                    stripped = follow_line.strip()
                    if not stripped:
                        continue
                    if stripped.startswith("PHY Mode:"):
                        break
                    if stripped.endswith(":"):
                        return stripped[:-1].strip()
                break
    return ""


def read_ssid_from_airport() -> str:
    import subprocess

    commands = [
        ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
    ]
    for cmd in commands:
        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        except (OSError, subprocess.CalledProcessError):
            continue
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line.startswith("SSID: "):
                return line.split(": ", 1)[1].strip()
    return ""


def resolve_path(config_dir: Path, value: str) -> Path:
    raw_path = Path(value).expanduser()
    if raw_path.is_absolute():
        return raw_path
    return config_dir / raw_path


def load_login_state(path: Path) -> datetime:
    if not path or not path.exists():
        return EPOCH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        timestamp = payload.get("last_successful_login")
        if not timestamp:
            return EPOCH
        return datetime.fromisoformat(timestamp)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logging.debug("Unable to read state file %s: %s", path, exc)
        return EPOCH


def save_login_state(path: Path, timestamp: datetime) -> None:
    payload = {"last_successful_login": timestamp.isoformat(timespec="seconds")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")
    except OSError as exc:
        logging.warning("Unable to write state file %s: %s", path, exc)


def parse_portal_response(text: str, callback: str) -> Dict[str, Any]:
    prefix = f"{callback}("
    normalized = text.strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1]
    if normalized.startswith(prefix) and normalized.endswith(")"):
        payload = normalized[len(prefix) : -1]
    else:
        match = JSONP_WRAPPER_RE.match(normalized)
        if match:
            normalized = match.group(1)
        payload = normalized
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        logging.debug("Unable to decode portal payload: %s", text)
        return {"raw": text}


def mask_account(username: str, suffix: str) -> str:
    head = username[:3]
    tail = username[-2:]
    return f"{head}***{tail}{suffix}"


def redact_text_secrets(text: str) -> str:
    redacted = text
    for key in SENSITIVE_LOG_KEYS:
        redacted = re.sub(
            rf"({re.escape(key)}=)[^&\s]+",
            r"\1***",
            redacted,
            flags=re.IGNORECASE,
        )
        redacted = re.sub(
            rf'("{re.escape(key)}"\s*:\s*")[^"]*(")',
            r"\1***\2",
            redacted,
            flags=re.IGNORECASE,
        )
        redacted = re.sub(
            rf"('{re.escape(key)}'\s*:\s*')[^']*(')",
            r"\1***\2",
            redacted,
            flags=re.IGNORECASE,
        )
    return redacted


def configure_logging(client: ClientProfile, verbose: bool) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = client.log_file
    if log_file:
        log_path = Path(log_file)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_path))
        except OSError as exc:
            print(f"Unable to open log file {log_path}: {exc}", file=sys.stderr)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )
    secret_filter = SensitiveDataFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(secret_filter)
    for handler in root_logger.handlers:
        handler.addFilter(secret_filter)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def build_dataclass(cls: Type[T], raw: Dict[str, Any], section: str) -> T:
    try:
        return cls(**raw.get(section, {}))
    except TypeError as exc:
        raise ValueError(f"Invalid [{section}] config: {exc}") from exc


def build_profiles(raw: Dict[str, Any]) -> tuple[Credentials, NetworkProfile, ClientProfile]:
    creds = build_dataclass(Credentials, raw, "credentials")
    network = build_dataclass(NetworkProfile, raw, "network")
    client = build_dataclass(ClientProfile, raw, "client")
    validate_profiles(creds, network, client)
    return creds, network, client


def validate_profiles(creds: Credentials, network: NetworkProfile, client: ClientProfile) -> None:
    if not creds.username.strip():
        raise ValueError("credentials.username cannot be empty")
    if not creds.password.strip():
        raise ValueError("credentials.password cannot be empty")
    if not network.portal_host.strip():
        raise ValueError("network.portal_host cannot be empty")
    if client.force_relogin_hours <= 0:
        raise ValueError("client.force_relogin_hours must be greater than 0")
    if client.check_interval_seconds <= 0:
        raise ValueError("client.check_interval_seconds must be greater than 0")
    if client.max_backoff_seconds <= 0:
        raise ValueError("client.max_backoff_seconds must be greater than 0")
    if client.relogin_cooldown_seconds < 0:
        raise ValueError("client.relogin_cooldown_seconds cannot be negative")
    if not client.state_file.strip():
        raise ValueError("client.state_file cannot be empty")
    for cidr in client.campus_ipv4_cidrs:
        try:
            network_obj = ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid client.campus_ipv4_cidrs entry {cidr!r}: {exc}") from exc
        if network_obj.version != 4:
            raise ValueError(f"client.campus_ipv4_cidrs entry must be IPv4: {cidr!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CSU portal auto re-login helper")
    parser.add_argument("--config", required=True, help="Path to config TOML")
    parser.add_argument("--once", action="store_true", help="Run a single probe/login and exit")
    parser.add_argument(
        "--force-relogin",
        action="store_true",
        help="Force one full refresh flow now, even if the state file says re-login is not due yet",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        print(f"Config file {config_path} not found", file=sys.stderr)
        return 1
    try:
        raw_config = load_config(config_path)
        creds, network, client = build_profiles(raw_config)
    except ValueError as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        return 1
    client.log_file = str(resolve_path(config_path.parent, client.log_file)) if client.log_file else ""
    client.state_file = str(resolve_path(config_path.parent, client.state_file))
    configure_logging(client, args.verbose)

    worker = PortalAutoLogin(creds, network, client, config_path.parent)
    worker.force_relogin_requested = args.force_relogin
    if args.once:
        return worker.run_once()
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
