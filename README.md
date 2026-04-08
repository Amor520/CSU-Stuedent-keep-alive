# CSU WiFi Auto Re-login

轻量、低打扰的 CSU 校园网自动重登录工具。核心目标只有两个：
- 首次运行就做一次真实“重新登录”；
- 之后只在第 6 天或意外掉线时再出手，尽量不常驻、不轮询、不耗电。

当前仓库分成两层：
- `auto_relogin.py`：真正的最小运行时。
- 其余抓包 / 可视化脚本：只在分析 portal 或演示时用，默认不进 macOS 安装包。

## 实现原理

### 1. 为什么不是“每 2 小时硬登录一次”
- 那样当然也能续命，但会更频繁地唤醒脚本、更多无意义请求，也更容易在你本来在线时制造瞬断。
- 现在的策略是“低频检查 + 到点才重登”：
  - 第一次运行：因为状态文件默认视为 Unix 时间戳 `0`，所以一定触发一次完整重登录。
  - 之后：只要距离上次成功登录还没到 `144` 小时（第 6 天），脚本就不主动踢线。
  - 但如果学校提前把你踢下线，脚本下次运行发现离线，也会直接补登录。
- 这样能把“主动操作次数”压到很低，同时避开第 7 天强退。

### 2. 为什么流程必须是 `unbind -> wait -> warmup -> login`
- 这是基于你这台机器实测抓包得出的，而不是拍脑袋写的。
- CSU 门户上，稳定成功的流程不是直接 `login`，而是：
  1. 先调 `mac/unbind`
  2. 等待 6 秒左右，让 portal 后端把旧会话清掉
  3. 预热 portal 根页面和登录页
  4. 再调 `/eportal/portal/login`
- 这么做的原因很简单：它更接近浏览器里的真实交互顺序，成功率也比“直接裸调 login”更稳。
- 如果 `mac/unbind` 不可用，脚本还保留 `logout` 回退路径。

### 3. 为什么不用“只看 Wi-Fi 名称”
- 只盯着某个 SSID，在校园网改名、设备拿不到 SSID、或开机早期系统还没上报 SSID 时，容易误判然后一直跳过。
- 现在默认主判断是本机 IPv4 是否落在 `100.64.0.0/10` 这样的校园网地址段里。
- `required_ssid` 还在，但变成可选辅助信号，不再是唯一门槛。
- 这对开机自启更稳，因为 launchd 拉起脚本时，IP 往往比 SSID 更早可用。

### 4. 为什么说它能耗很低
- 推荐运行方式不是常驻 daemon，而是 macOS `launchd`：
  - 登录系统时跑一次
  - 之后每 `18000` 秒，也就是每 5 小时跑一次
- 绝大多数时间根本没有常驻 Python 进程。
- 每次运行只做几件很小的事：
  - 读本地状态文件
  - 判断当前 IP/网络
  - 必要时发 1~4 个 HTTPS GET 请求
  - 写回一个小 JSON 状态文件
- 所以从资源模型上看，它已经接近“能不醒就不醒”的最简方案了。严格说我不敢承诺“绝对最低”，但对这个需求来说，已经是非常低功耗、非常低打扰的实现。

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

### macOS 安装包构建
如果你想直接产出一个可安装的 `.pkg`：
```bash
./installer/macos/build_installer.sh
```

构建完成后会在 `dist/` 下生成类似：
```text
dist/CSUStudentWiFi-1.1.2.pkg
```

安装包会放入这些最小运行时文件：
- `/Library/Application Support/CSUStudentWiFi/bin/csu-auto-relogin`
- `/Library/Application Support/CSUStudentWiFi/config.example.toml`
- `/Library/Application Support/CSUStudentWiFi/setup_launch_agent.sh`
- `/Library/Application Support/CSUStudentWiFi/disable_launch_agent.sh`
- `/Library/Application Support/CSUStudentWiFi/open_config.sh`
- `/Library/Application Support/CSUStudentWiFi/open_setup_wizard.sh`

安装后的默认行为：
- 自动在当前用户目录下准备 `~/Library/Application Support/CSUStudentWiFi/config.toml`
- 自动生成 `~/Library/LaunchAgents/cn.csu.autorelogin.plist`
- 如果检测到配置里已经不是占位账号/密码，就会自动加载 LaunchAgent
- 如果还是示例配置，就只准备文件，不会盲目上线

### 安装后的可视化设置页
如果你已经安装好了 `.pkg`，现在可以直接开本地设置页：

```bash
"/Library/Application Support/CSUStudentWiFi/open_setup_wizard.sh"
```

它会自动打开一个本地网页，把下面这 3 步合成一个可视化流程：
- 默认只填账号 / 密码
- 保存配置并启用自动运行
- 立即执行一次真实测试，并在页面里看结果

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

## 文件说明
- `auto_relogin.py`：核心运行脚本，真正必须保留的只有它。
- `config.example.toml`：示例配置。
- `launchd/csu.autorelogin.plist.example`：源码方式部署时的 LaunchAgent 模板。
- `installer/macos/`：macOS 安装包构建脚本和安装后辅助脚本。
- `capture_chrome_requests.mjs`、`parse_portal_capture.py`、`start_portal_capture.sh`：抓 portal 请求时用。
- `live_relogin_dashboard.py`、`render_relogin_report.py`、`visual_verify_*.sh`：做可视化验证和在线演示时用。

## 安全提示
- 配置文件含有明文密码，请设置 600 权限并避免上传版本库。
- 项目自带 `.gitignore`，已默认忽略 `config.toml`、日志、状态文件和虚拟环境。
- HTTPS 请求默认校验证书，除非你明确知道证书问题，否则不要改成 `verify_certificate=false`。
- 自动脚本只能在 CSU 网络环境内运行，Portal 仅对 10.x/100.x 内网开放。

## 调试建议
- 浏览器 Network 面板同时抓 `login` 和 `logout` 请求，确认参数与学校真实门户一致，尤其是登出参数。
- 如果脚本久等无响应，可加 `--verbose` 看日志或将 `check_interval_seconds` 调小。
- 观察学校自助系统在线终端列表，验证脚本是否成功上线/是否占满 3 台额度。
