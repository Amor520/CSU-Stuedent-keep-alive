# CSU WiFi Auto Re-login

轻量脚本，帮助在校园网 7 天强制下线或掉线时自动重新登录 `portal.csu.edu.cn:802`。

## 快速开始
1. 安装依赖：
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. 复制配置并填写真实参数（账号/密码/后缀、检查 URL 等）：
   ```bash
   cp config.example.toml config.toml
   $EDITOR config.toml
   ```
3. 先在浏览器抓包确认账号后缀、`wlan_ac_ip`、`callback` 等参数，再写入配置；CSU 当前门户实测登录/解绑使用全 0 MAC，所以默认将 `mac_override` 设为 `000000000000`。
4. 现在默认优先按校园网 IP 段判断是否执行；`client.required_ssid` 变成可选辅助条件，留空时不会因为 Wi-Fi 名称变化而误跳过。
5. 启动脚本：
   ```bash
   python auto_relogin.py --config config.toml
   ```
   - `--once`: 只执行一次探测/登录，适合调试。
   - `--verbose`: 打印 DEBUG 日志。
6. 现在默认行为是：如果状态文件不存在，脚本会把“上次成功登录时间”当作 Unix 纪元 `0`，因此第一次运行一定会主动执行一次“先登出再登录”的重登录流程。
7. 如果你担心重登录瞬间断网影响当前会话，可以运行 `./relogin_retry.sh`。它会在本地持续重试：SSID 不对就等待，Portal 失败就短间隔重试，直到成功或达到最大次数。
8. 如果你想看一份可视化验证报告，可以运行 `./visual_verify_once.sh`。它会真实执行一次 `--once`，随后自动生成并打开 HTML 时间线报告，方便你肉眼确认“是否无感、何时解绑、何时重新登录”。
9. 如果你想看“动态实时观测”效果，可以运行 `./visual_verify_live.sh`。它会启动一个本地实时页面；页面里有“在线演示 开始测试”按钮，点一下就会强制执行一次真实重登录演示，并每秒刷新时间线和状态卡片。

### macOS 定时巡检（启动一次 + 每 5 小时）
1. 确保 `.venv/bin/python`、`config.toml` 路径正确，并复制模板：
   ```bash
   cp launchd/csu.autorelogin.plist.example ~/Library/LaunchAgents/cn.csu.autorelogin.plist
   ```
2. 按需编辑 `~/Library/LaunchAgents/cn.csu.autorelogin.plist`：
   - `ProgramArguments` 中的 Python、脚本、配置路径替换成你实际的绝对路径；保持 `--once` 让脚本运行一次后退出。
   - `StartInterval` 设为 `18000` 秒即可实现“启动 RunAtLoad 一次 + 之后每 5h 再跑一次”。
3. 加载并立即触发一次：
   ```bash
   launchctl unload ~/Library/LaunchAgents/cn.csu.autorelogin.plist 2>/dev/null || true
   launchctl load ~/Library/LaunchAgents/cn.csu.autorelogin.plist
   ```
   LaunchAgent 会在你登录 macOS 时自动启动一次，此后每隔 18000 秒再运行脚本一次，期间不常驻进程，能耗比每 2 小时巡检更低。
4. 当前推荐策略是：首次运行强制做一次重登录；之后只在脚本启动时检查本地时间戳，若距离上次成功登录已满 `144` 小时，就再次执行“先解绑/下线再登录”。
5. 现在默认只要本机 IPv4 落在 `client.campus_ipv4_cidrs` 里就会继续执行；如果你额外配置了 `client.required_ssid`，脚本会优先认这个 SSID，但 SSID 不匹配时仍可回退到校园网 IP 判断。
6. 这类低频方案的代价是：如果学校临时把你踢下线，而时间戳还没到第 6 天，那么最坏要等到下一次 5 小时巡检才会自动恢复。它更省电，但没有高频巡检那么即时。

## 实现思路
- 每次脚本启动先读取 `auto_relogin_state.json`；如果文件不存在，就把上次登录时间视为 Unix 纪元 `0`，从而在第一次运行时必定触发重登录。
- 在 macOS 上，脚本会优先判断当前 IPv4 是否落在 `client.campus_ipv4_cidrs`（默认 `100.64.0.0/10`）内；`client.required_ssid` 只作为辅助信号，避免校园网 SSID 改名后开机自启一直被跳过。
- 当距离上次成功登录超过 `force_relogin_hours`（默认 144h）时，如果当前仍在线，脚本会优先请求 `https://portal.csu.edu.cn:802/eportal/portal/mac/unbind`，等待 `relogin_cooldown_seconds`（默认 6 秒）后预热一次 portal 页面，再调用 `https://portal.csu.edu.cn:802/eportal/portal/login` 完成重登录；如果 `mac/unbind` 失败，再回退到 `logout`。
- 如果当前不在线，即使没到第 6 天，也会直接尝试登录，兼顾意外掉线后的恢复。
- `wlan_user_ip` 自动从本地 UDP socket 获取；`wlan_user_mac` 现默认覆盖为 `000000000000` 以匹配 CSU 当前门户实测行为，也可自行改回真实 MAC。
- 登录成功将记录时间戳与消息，可在 `auto_relogin.log` 中查看。
- 上次成功登录时间会写入 `auto_relogin_state.json`，因此即使用 `launchd` 每次只执行 `--once`，脚本也能记住会话年龄。
- `check_interval_seconds` 仍保留给 `run_forever` 模式；如果你只用 macOS 的 `launchd`，核心调度由 `RunAtLoad + StartInterval=18000` 完成。

## 守护模式 / 开机自启
- macOS/Linux 可借助 `launchd`、`systemd --user` 或 `cron @reboot` 调用 `auto_relogin.py --config …`。
- 运行在旁路软路由时建议使用 `screen`/`tmux` 保持脚本后台运行。

## 安全提示
- 配置文件含有明文密码，请设置 600 权限并避免上传版本库。
- 项目自带 `.gitignore`，已默认忽略 `config.toml`、日志、状态文件和虚拟环境。
- HTTPS 请求默认校验证书，除非你明确知道证书问题，否则不要改成 `verify_certificate=false`。
- 自动脚本只能在 CSU 网络环境内运行，Portal 仅对 10.x/100.x 内网开放。

## 调试建议
- 浏览器 Network 面板同时抓 `login` 和 `logout` 请求，确认参数与学校真实门户一致，尤其是登出参数。
- 如果脚本久等无响应，可加 `--verbose` 看日志或将 `check_interval_seconds` 调小。
- 观察学校自助系统在线终端列表，验证脚本是否成功上线/是否占满 3 台额度。
