import SwiftUI
import Foundation
import Darwin

struct SetupConfig {
    var username = ""
    var password = ""
    var accountSuffix = "@cmccn"
    var acIP = ""
    var acName = ""
    var requiredSSID = ""
    var campusCIDRs = "100.64.0.0/10"
    var forceReloginHours = "144"
    var reloginCooldownSeconds = "6"
    var interfaceName = ""
    var macOverride = "000000000000"
}

enum StatusTone {
    case normal
    case warn
    case bad
    case good
}

@MainActor
final class SetupViewModel: ObservableObject {
    let appSupportDir = URL(fileURLWithPath: "/Library/Application Support/CSUStudentWiFi", isDirectory: true)
    let userSupportDir = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/CSUStudentWiFi", isDirectory: true)

    @Published var config = SetupConfig()
    @Published var showAdvanced = false
    @Published var configPathText = ""
    @Published var statePathText = ""
    @Published var logPathText = ""
    @Published var autoRunText = "未开启"
    @Published var configStateText = "还没填完整"
    @Published var lastTestText = "你还没有执行过测试"
    @Published var pageStatus = "正在读取当前状态..."
    @Published var pageStatusTone: StatusTone = .warn
    @Published var testStatus = "还没有开始测试。"
    @Published var testStatusTone: StatusTone = .warn
    @Published var testOutput = "等待操作..."
    @Published var isTesting = false
    @Published var lastExitCode: Int?
    @Published var lastFinishedAt = ""
    @Published var lastStartedAt = ""
    @Published var lastRunOutput = ""

    private let notesText = """
推荐顺序：先保存配置，再启用自动运行，最后点“立即测试一次”。

“立即测试一次”会直接强制执行一次真实重新登录，不会参考本地时间戳。
如果测试时你本来就在线，脚本会先解绑再重新登录，所以可能会有几秒短暂断网，这是正常现象。
"""

    var configURL: URL {
        userSupportDir.appendingPathComponent("config.toml")
    }

    var stateURL: URL {
        userSupportDir.appendingPathComponent("auto_relogin_state.json")
    }

    var logURL: URL {
        userSupportDir.appendingPathComponent("auto_relogin.log")
    }

    var setupScriptURL: URL {
        appSupportDir.appendingPathComponent("setup_launch_agent.sh")
    }

    var disableScriptURL: URL {
        appSupportDir.appendingPathComponent("disable_launch_agent.sh")
    }

    var runnerURL: URL {
        appSupportDir.appendingPathComponent("bin/csu-auto-relogin")
    }

    var notes: String {
        notesText
    }

    func loadInitialState() {
        ensureUserConfig()
        loadConfig()
        refreshRuntimeState()
    }

    func refreshRuntimeState() {
        configPathText = configURL.path
        statePathText = stateURL.path
        logPathText = logURL.path
        configStateText = isConfigReady ? "已经可用" : "还没填完整"
        autoRunText = isLaunchAgentLoaded() ? "已经开启" : "还没开启"
        lastTestText = describeLastTest()
        pageStatus = """
配置文件：\(configPathText)
自动运行：\(autoRunText)
最近测试：\(describeLastTest())
当前建议：\(isConfigReady ? "可以直接启用自动运行，或者先再点一次测试确认。" : "先把账号和密码填好，然后点“保存配置”。")
"""
        pageStatusTone = isConfigReady ? .good : .warn
        if !isTesting {
            testStatus = describeLastTest()
            testStatusTone = toneForLastTest()
        }
        let chunks = [currentOutputChunk(), currentLogChunk()].filter { !$0.isEmpty }
        testOutput = chunks.isEmpty ? "等待操作..." : chunks.joined(separator: "\n\n")
    }

    func saveConfig() {
        ensureUserConfigDirectory()
        let rendered = renderConfig()
        do {
            try rendered.write(to: configURL, atomically: true, encoding: .utf8)
            chmod(configURL.path, 0o600)
            pageStatus = """
配置已保存到：
\(configURL.path)

默认中国移动后缀会自动保留。
下一步直接点“启用自动运行”，或者先点“立即测试一次”。
"""
            pageStatusTone = .good
            refreshRuntimeState()
        } catch {
            pageStatus = "保存失败：\(error.localizedDescription)"
            pageStatusTone = .bad
        }
    }

    func enableAutostart() {
        runAuxiliaryCommand(
            executable: setupScriptURL,
            arguments: ["--load-if-ready"],
            successPrefix: "自动运行已处理"
        )
    }

    func disableAutostart() {
        runAuxiliaryCommand(
            executable: disableScriptURL,
            arguments: [],
            successPrefix: "自动运行已停用"
        )
    }

    func runImmediateTest() {
        if isTesting {
            pageStatus = "已经有一个测试在运行，请稍等。"
            pageStatusTone = .warn
            return
        }
        if !isConfigReady {
            pageStatus = "配置还没填完整。现在默认只需要账号和密码。"
            pageStatusTone = .warn
            return
        }
        isTesting = true
        lastStartedAt = timestampNow()
        testStatus = "测试中：\(lastStartedAt)"
        testStatusTone = .normal
        lastRunOutput = ""
        testOutput = "正在执行真实重新登录，请稍等..."

        let executable = runnerURL
        let args = ["--config", configURL.path, "--once", "--force-relogin", "--verbose"]
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Self.runProcess(executable: executable, arguments: args)
            DispatchQueue.main.async {
                self.isTesting = false
                self.lastExitCode = Int(result.exitCode)
                self.lastFinishedAt = self.timestampNow()
                self.lastRunOutput = result.output
                self.lastTestText = self.describeLastTest()
                self.testStatus = self.describeLastTest()
                self.testStatusTone = self.toneForLastTest()
                let chunks = [
                    result.output.isEmpty ? "" : "[本次测试输出]\n\(result.output)",
                    self.currentLogChunk(),
                ].filter { !$0.isEmpty }
                self.testOutput = chunks.isEmpty ? "等待操作..." : chunks.joined(separator: "\n\n")
                self.refreshRuntimeState()
            }
        }
    }

    private var isConfigReady: Bool {
        let username = config.username.trimmingCharacters(in: .whitespacesAndNewlines)
        let password = config.password.trimmingCharacters(in: .whitespacesAndNewlines)
        if username.isEmpty || password.isEmpty {
            return false
        }
        if username == "20211234567" || password == "replace-with-real-password" {
            return false
        }
        return true
    }

    private func ensureUserConfigDirectory() {
        try? FileManager.default.createDirectory(at: userSupportDir, withIntermediateDirectories: true)
    }

    private func ensureUserConfig() {
        ensureUserConfigDirectory()
        guard !FileManager.default.fileExists(atPath: configURL.path) else {
            chmod(configURL.path, 0o600)
            return
        }

        let source = appSupportDir.appendingPathComponent("config.example.toml")
        guard let text = try? String(contentsOf: source, encoding: .utf8) else {
            let fallback = renderConfig()
            try? fallback.write(to: configURL, atomically: true, encoding: .utf8)
            chmod(configURL.path, 0o600)
            return
        }

        let replaced = text
            .replacingOccurrences(of: #"state_file = "auto_relogin_state.json""#, with: #"state_file = "\#(stateURL.path)""#)
            .replacingOccurrences(of: #"log_file = "auto_relogin.log""#, with: #"log_file = "\#(logURL.path)""#)
        try? replaced.write(to: configURL, atomically: true, encoding: .utf8)
        chmod(configURL.path, 0o600)
    }

    private func loadConfig() {
        guard let text = try? String(contentsOf: configURL, encoding: .utf8) else {
            return
        }

        var loaded = SetupConfig()
        loaded.username = quotedValue(for: "username", in: text) ?? loaded.username
        loaded.password = quotedValue(for: "password", in: text) ?? loaded.password
        loaded.accountSuffix = quotedValue(for: "account_suffix", in: text) ?? loaded.accountSuffix
        loaded.acIP = quotedValue(for: "ac_ip", in: text) ?? loaded.acIP
        loaded.acName = quotedValue(for: "ac_name", in: text) ?? loaded.acName
        loaded.requiredSSID = quotedValue(for: "required_ssid", in: text) ?? loaded.requiredSSID
        loaded.interfaceName = quotedValue(for: "interface", in: text) ?? loaded.interfaceName
        loaded.macOverride = quotedValue(for: "mac_override", in: text) ?? loaded.macOverride
        loaded.forceReloginHours = numericValue(for: "force_relogin_hours", in: text) ?? loaded.forceReloginHours
        loaded.reloginCooldownSeconds = numericValue(for: "relogin_cooldown_seconds", in: text) ?? loaded.reloginCooldownSeconds
        loaded.campusCIDRs = listValue(for: "campus_ipv4_cidrs", in: text) ?? loaded.campusCIDRs
        config = loaded
    }

    private func renderConfig() -> String {
        let cidrs = config.campusCIDRs
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        let cidrText = (cidrs.isEmpty ? ["100.64.0.0/10"] : cidrs)
            .map { "\"\($0)\"" }
            .joined(separator: ", ")
        let safeSuffix = config.accountSuffix.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "@cmccn" : config.accountSuffix.trimmingCharacters(in: .whitespacesAndNewlines)
        let safeForce = sanitizeInteger(config.forceReloginHours, fallback: 144, minimum: 1)
        let safeCooldown = sanitizeInteger(config.reloginCooldownSeconds, fallback: 6, minimum: 0)
        let safeMac = config.macOverride.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "000000000000" : config.macOverride.trimmingCharacters(in: .whitespacesAndNewlines)

        return """
[credentials]
username = "\(escaped(config.username))"
password = "\(escaped(config.password))"
account_suffix = "\(escaped(safeSuffix))"

[network]
portal_host = "portal.csu.edu.cn"
portal_port = 802
login_method = 1
callback = "dr1004"
ac_ip = "\(escaped(config.acIP.trimmingCharacters(in: .whitespacesAndNewlines)))"
ac_name = "\(escaped(config.acName.trimmingCharacters(in: .whitespacesAndNewlines)))"
terminal_type = 1
check_url = "http://connectivitycheck.gstatic.com/generate_204"
fallback_check_url = "http://www.baidu.com"
verify_certificate = true
prefer_mac_unbind = true
unbind_callback = "dr1002"
logout_user_account = "drcom"
logout_user_password = "123"
logout_ac_logout = 1
logout_register_mode = 1
logout_user_ipv6 = ""
logout_vlan_id = 0

[client]
check_interval_seconds = 45
force_relogin_hours = \(safeForce)
relogin_cooldown_seconds = \(safeCooldown)
max_backoff_seconds = 300
log_file = "\(escaped(logURL.path))"
state_file = "\(escaped(stateURL.path))"
interface = "\(escaped(config.interfaceName.trimmingCharacters(in: .whitespacesAndNewlines)))"
mac_override = "\(escaped(safeMac))"
required_ssid = "\(escaped(config.requiredSSID.trimmingCharacters(in: .whitespacesAndNewlines)))"
campus_ipv4_cidrs = [\(cidrText)]
"""
    }

    private func runAuxiliaryCommand(executable: URL, arguments: [String], successPrefix: String) {
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Self.runProcess(executable: executable, arguments: arguments)
            DispatchQueue.main.async {
                if result.exitCode == 0 {
                    self.pageStatus = "\(successPrefix)\n\n\(result.output.isEmpty ? "完成" : result.output)"
                    self.pageStatusTone = .good
                } else {
                    self.pageStatus = "\(successPrefix)失败：\(result.output.isEmpty ? "exit=\(result.exitCode)" : result.output)"
                    self.pageStatusTone = .bad
                }
                self.refreshRuntimeState()
            }
        }
    }

    private func currentOutputChunk() -> String {
        guard !isTesting else {
            return "[本次测试输出]\n正在执行真实重新登录，请稍等..."
        }
        if let code = lastExitCode, !testStatus.isEmpty, testStatus != "还没有开始测试。" {
            if !lastRunOutput.isEmpty {
                return "[本次测试输出]\n\(lastRunOutput)"
            }
            return "[本次测试输出]\n最近测试结束：\(code)"
        }
        return ""
    }

    private func currentLogChunk() -> String {
        let tail = tailText(logURL, limit: 80)
        return tail.isEmpty ? "" : "[最近日志]\n\(tail)"
    }

    private func describeLastTest() -> String {
        if isTesting {
            return "正在测试（开始于 \(lastStartedAt.isEmpty ? "刚刚" : lastStartedAt)）"
        }
        guard let exitCode = lastExitCode else {
            return "你还没有执行过测试"
        }
        if exitCode == 0 {
            return "最近一次测试成功\(lastFinishedAt.isEmpty ? "" : "，完成于 \(lastFinishedAt)")"
        }
        if exitCode == 3 {
            return "最近一次测试被跳过\(lastFinishedAt.isEmpty ? "" : "，完成于 \(lastFinishedAt)")"
        }
        return "最近一次测试失败（exit=\(exitCode)）\(lastFinishedAt.isEmpty ? "" : "，完成于 \(lastFinishedAt)")"
    }

    private func toneForLastTest() -> StatusTone {
        if isTesting {
            return .normal
        }
        guard let exitCode = lastExitCode else {
            return .warn
        }
        if exitCode == 0 {
            return .good
        }
        if exitCode == 3 {
            return .warn
        }
        return .bad
    }

    private func isLaunchAgentLoaded() -> Bool {
        let result = Self.runProcess(
            executable: URL(fileURLWithPath: "/bin/zsh"),
            arguments: ["-lc", "launchctl list | grep -F cn.csu.autorelogin >/dev/null 2>&1"]
        )
        return result.exitCode == 0
    }

    private func quotedValue(for key: String, in text: String) -> String? {
        let pattern = #"(?m)^\#(key)\s*=\s*"([^"]*)""#
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return nil
        }
        let nsText = text as NSString
        let range = NSRange(location: 0, length: nsText.length)
        guard let match = regex.firstMatch(in: text, range: range), match.numberOfRanges > 1 else {
            return nil
        }
        return nsText.substring(with: match.range(at: 1))
    }

    private func numericValue(for key: String, in text: String) -> String? {
        let pattern = #"(?m)^\#(key)\s*=\s*([0-9]+)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return nil
        }
        let nsText = text as NSString
        let range = NSRange(location: 0, length: nsText.length)
        guard let match = regex.firstMatch(in: text, range: range), match.numberOfRanges > 1 else {
            return nil
        }
        return nsText.substring(with: match.range(at: 1))
    }

    private func listValue(for key: String, in text: String) -> String? {
        let pattern = #"(?m)^\#(key)\s*=\s*\[(.*)\]"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return nil
        }
        let nsText = text as NSString
        let range = NSRange(location: 0, length: nsText.length)
        guard let match = regex.firstMatch(in: text, range: range), match.numberOfRanges > 1 else {
            return nil
        }
        let body = nsText.substring(with: match.range(at: 1))
        let items = body
            .split(separator: ",")
            .map { $0.replacingOccurrences(of: "\"", with: "").trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        return items.joined(separator: ", ")
    }

    private func sanitizeInteger(_ value: String, fallback: Int, minimum: Int) -> Int {
        let parsed = Int(value.trimmingCharacters(in: .whitespacesAndNewlines)) ?? fallback
        return max(minimum, parsed)
    }

    private func escaped(_ value: String) -> String {
        value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }

    private func timestampNow() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter.string(from: Date())
    }

    private func tailText(_ url: URL, limit: Int) -> String {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else {
            return ""
        }
        let lines = text.split(whereSeparator: \.isNewline)
        return lines.suffix(limit).joined(separator: "\n")
    }

    nonisolated private static func runProcess(executable: URL, arguments: [String]) -> (output: String, exitCode: Int32) {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
        } catch {
            return ("\(error.localizedDescription)", 1)
        }
        process.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let text = String(data: data, encoding: .utf8) ?? ""
        return (text.trimmingCharacters(in: .whitespacesAndNewlines), process.terminationStatus)
    }
}

struct StatusCard: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Color(red: 0.42, green: 0.47, blue: 0.56))
            Text(value)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(Color(red: 0.09, green: 0.13, blue: 0.2))
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(16)
        .background(Color(red: 0.97, green: 0.98, blue: 0.99))
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color(red: 0.89, green: 0.91, blue: 0.95), lineWidth: 1)
        )
    }
}

struct ToneBox: View {
    let text: String
    let tone: StatusTone

    var colors: (Color, Color, Color) {
        switch tone {
        case .good:
            return (
                Color(red: 0.93, green: 0.99, blue: 0.95),
                Color(red: 0.81, green: 0.93, blue: 0.85),
                Color(red: 0.11, green: 0.38, blue: 0.2)
            )
        case .warn:
            return (
                Color(red: 1.0, green: 0.97, blue: 0.92),
                Color(red: 0.96, green: 0.84, blue: 0.67),
                Color(red: 0.64, green: 0.37, blue: 0.07)
            )
        case .bad:
            return (
                Color(red: 0.99, green: 0.95, blue: 0.95),
                Color(red: 0.98, green: 0.8, blue: 0.8),
                Color(red: 0.63, green: 0.13, blue: 0.13)
            )
        case .normal:
            return (
                Color(red: 0.94, green: 0.96, blue: 1.0),
                Color(red: 0.83, green: 0.88, blue: 0.97),
                Color(red: 0.16, green: 0.27, blue: 0.47)
            )
        }
    }

    var body: some View {
        Text(text)
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(colors.2)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(colors.0)
            .clipShape(RoundedRectangle(cornerRadius: 18))
            .overlay(
                RoundedRectangle(cornerRadius: 18)
                    .stroke(colors.1, lineWidth: 1)
            )
    }
}

struct ActionButtonStyle: ButtonStyle {
    let fill: Color
    let text: Color
    let border: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .bold))
            .foregroundStyle(text)
            .padding(.horizontal, 18)
            .padding(.vertical, 13)
            .background(fill)
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(border, lineWidth: 1)
            )
            .scaleEffect(configuration.isPressed ? 0.985 : 1.0)
            .shadow(color: Color.black.opacity(configuration.isPressed ? 0.02 : 0.06), radius: 10, x: 0, y: 6)
    }
}

struct FieldCard<Content: View>: View {
    let title: String
    let hint: String?
    let content: Content

    init(title: String, hint: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.hint = hint
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Color(red: 0.09, green: 0.13, blue: 0.2))
            content
            if let hint {
                Text(hint)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(red: 0.42, green: 0.47, blue: 0.56))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

struct ContentView: View {
    @StateObject private var model = SetupViewModel()
    private let timer = Timer.publish(every: 1.5, on: .main, in: .common).autoconnect()

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                heroSection
                HStack(alignment: .top, spacing: 20) {
                    leftPanel
                    rightPanel
                }
            }
            .padding(24)
        }
        .frame(minWidth: 1180, minHeight: 780)
        .background(Color(red: 0.96, green: 0.97, blue: 0.99))
        .onAppear {
            model.loadInitialState()
        }
        .onReceive(timer) { _ in
            model.refreshRuntimeState()
        }
    }

    var heroSection: some View {
        HStack(alignment: .top, spacing: 20) {
            VStack(alignment: .leading, spacing: 16) {
                Text("CSU Wi-Fi 设置中心")
                    .font(.system(size: 34, weight: .bold))
                    .foregroundStyle(Color(red: 0.09, green: 0.13, blue: 0.2))
                Text("现在它是一个原生程序窗口，不再依赖浏览器。你只需要填账号和密码，保存之后就能启用自动运行，并在这里直接完成一次真实测试。")
                    .font(.system(size: 15))
                    .foregroundStyle(Color(red: 0.42, green: 0.47, blue: 0.56))
                    .lineSpacing(4)
                HStack(spacing: 10) {
                    chip("步骤 1：填写账号")
                    chip("步骤 2：保存配置")
                    chip("步骤 3：启用自动运行")
                    chip("步骤 4：立即测试")
                }
                .fixedSize(horizontal: false, vertical: true)
                ToneBox(
                    text: "默认按中国移动处理，不用再手动输入运营商后缀、AC IP、AC 名称。只有你以后想微调高级行为时，再展开高级选项即可。",
                    tone: .normal
                )
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
            .background(Color.white)
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .overlay(
                RoundedRectangle(cornerRadius: 24)
                    .stroke(Color(red: 0.89, green: 0.91, blue: 0.95), lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(0.06), radius: 20, x: 0, y: 8)

            VStack(alignment: .leading, spacing: 14) {
                Text("当前概览")
                    .font(.system(size: 23, weight: .bold))
                Text("这里会实时告诉你：配置是否完成、自动运行是否开启，以及最近一次测试结果。")
                    .font(.system(size: 14))
                    .foregroundStyle(Color(red: 0.42, green: 0.47, blue: 0.56))
                    .lineSpacing(3)
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                    StatusCard(title: "配置文件", value: model.configPathText)
                    StatusCard(title: "状态文件", value: model.statePathText)
                    StatusCard(title: "日志文件", value: model.logPathText)
                    StatusCard(title: "开机自动运行", value: model.autoRunText)
                    StatusCard(title: "配置状态", value: model.configStateText)
                    StatusCard(title: "最近测试", value: model.lastTestText)
                }
            }
            .frame(width: 390, alignment: .leading)
            .padding(24)
            .background(Color.white)
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .overlay(
                RoundedRectangle(cornerRadius: 24)
                    .stroke(Color(red: 0.89, green: 0.91, blue: 0.95), lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(0.06), radius: 20, x: 0, y: 8)
        }
    }

    var leftPanel: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("基础设置")
                .font(.system(size: 23, weight: .bold))
            Text("按你的目标，默认只需要填账号和密码。其他内容都已经替你收起来了。")
                .font(.system(size: 14))
                .foregroundStyle(Color(red: 0.42, green: 0.47, blue: 0.56))

            HStack(spacing: 16) {
                FieldCard(title: "校园网账号") {
                    TextField("例如 8208231325", text: $model.config.username)
                        .textFieldStyle(.plain)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 14)
                        .background(Color.white)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color(red: 0.84, green: 0.88, blue: 0.93), lineWidth: 1))
                }
                FieldCard(title: "默认运营商", hint: "默认按中国移动处理；如果以后想改联通/电信，在下方高级选项里再改。") {
                    Text("中国移动（默认 @cmccn）")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 14)
                        .background(Color(red: 0.98, green: 0.98, blue: 0.99))
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color(red: 0.84, green: 0.88, blue: 0.93), lineWidth: 1))
                }
            }

            FieldCard(title: "校园网密码") {
                SecureField("输入真实密码", text: $model.config.password)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 14)
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color(red: 0.84, green: 0.88, blue: 0.93), lineWidth: 1))
            }

            DisclosureGroup(isExpanded: $model.showAdvanced) {
                VStack(spacing: 16) {
                    HStack(spacing: 16) {
                        FieldCard(title: "运营商后缀") {
                            TextField("@cmccn", text: $model.config.accountSuffix)
                                .textFieldStyle(.roundedBorder)
                        }
                        FieldCard(title: "限定 Wi-Fi 名称（可选）") {
                            TextField("留空则主要按校园网 IP 判断", text: $model.config.requiredSSID)
                                .textFieldStyle(.roundedBorder)
                        }
                    }
                    HStack(spacing: 16) {
                        FieldCard(title: "AC IP（可选）") {
                            TextField("现在默认不用填", text: $model.config.acIP)
                                .textFieldStyle(.roundedBorder)
                        }
                        FieldCard(title: "AC 名称（可选）") {
                            TextField("现在默认不用填", text: $model.config.acName)
                                .textFieldStyle(.roundedBorder)
                        }
                    }
                    HStack(spacing: 16) {
                        FieldCard(title: "校园网 IPv4 段") {
                            TextField("100.64.0.0/10", text: $model.config.campusCIDRs)
                                .textFieldStyle(.roundedBorder)
                        }
                        FieldCard(title: "第几小时主动重登") {
                            TextField("144", text: $model.config.forceReloginHours)
                                .textFieldStyle(.roundedBorder)
                        }
                    }
                    HStack(spacing: 16) {
                        FieldCard(title: "解绑后等待秒数") {
                            TextField("6", text: $model.config.reloginCooldownSeconds)
                                .textFieldStyle(.roundedBorder)
                        }
                        FieldCard(title: "网卡名（可选）") {
                            TextField("例如 en0", text: $model.config.interfaceName)
                                .textFieldStyle(.roundedBorder)
                        }
                    }
                    FieldCard(title: "MAC 覆盖值") {
                        TextField("000000000000", text: $model.config.macOverride)
                            .textFieldStyle(.roundedBorder)
                    }
                }
                .padding(.top, 16)
            } label: {
                Text("高级选项（通常不用填）")
                    .font(.system(size: 16, weight: .semibold))
            }
            .padding(18)
            .background(Color(red: 0.98, green: 0.99, blue: 1.0))
            .clipShape(RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(Color(red: 0.89, green: 0.91, blue: 0.95), lineWidth: 1))

            FieldCard(title: "使用说明") {
                TextEditor(text: .constant(model.notes))
                    .font(.system(size: 14))
                    .scrollContentBackground(.hidden)
                    .background(Color(red: 0.98, green: 0.98, blue: 0.99))
                    .frame(minHeight: 122)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color(red: 0.89, green: 0.91, blue: 0.95), lineWidth: 1))
                    .disabled(true)
            }

            ToneBox(
                text: "推荐顺序：先点“保存配置”，再点“启用自动运行”，最后点“立即测试一次”。这里的“立即测试一次”会强制重新登录，不会参考本地时间戳。",
                tone: .normal
            )

            HStack(spacing: 12) {
                Button("1. 保存配置") {
                    model.saveConfig()
                }
                .buttonStyle(ActionButtonStyle(
                    fill: Color(red: 0.15, green: 0.39, blue: 0.92),
                    text: .white,
                    border: Color(red: 0.15, green: 0.39, blue: 0.92)
                ))

                Button("2. 启用自动运行") {
                    model.enableAutostart()
                }
                .buttonStyle(ActionButtonStyle(
                    fill: .white,
                    text: Color(red: 0.16, green: 0.27, blue: 0.47),
                    border: Color(red: 0.85, green: 0.89, blue: 0.95)
                ))

                Button("3. 立即测试一次") {
                    model.runImmediateTest()
                }
                .buttonStyle(ActionButtonStyle(
                    fill: Color(red: 0.15, green: 0.39, blue: 0.92),
                    text: .white,
                    border: Color(red: 0.15, green: 0.39, blue: 0.92)
                ))

                Button("停用自动运行") {
                    model.disableAutostart()
                }
                .buttonStyle(ActionButtonStyle(
                    fill: .white,
                    text: Color(red: 0.6, green: 0.2, blue: 0.1),
                    border: Color(red: 0.99, green: 0.84, blue: 0.7)
                ))
            }

            ToneBox(text: model.pageStatus, tone: model.pageStatusTone)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(24)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .overlay(
            RoundedRectangle(cornerRadius: 24)
                .stroke(Color(red: 0.89, green: 0.91, blue: 0.95), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.06), radius: 20, x: 0, y: 8)
    }

    var rightPanel: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("测试与日志")
                .font(.system(size: 23, weight: .bold))
            Text("这里会显示“立即测试一次”的实时结果，以及最近日志片段。测试成功后，你能直接看到解绑、等待、预热和重新登录的全过程。")
                .font(.system(size: 14))
                .foregroundStyle(Color(red: 0.42, green: 0.47, blue: 0.56))
                .lineSpacing(3)

            ToneBox(text: model.testStatus, tone: model.testStatusTone)

            ScrollView {
                Text(model.testOutput)
                    .font(.system(size: 14, weight: .medium, design: .monospaced))
                    .foregroundStyle(Color(red: 0.14, green: 0.2, blue: 0.29))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(16)
            }
            .frame(maxWidth: .infinity, minHeight: 520, maxHeight: .infinity)
            .background(Color(red: 0.98, green: 0.98, blue: 0.99))
            .clipShape(RoundedRectangle(cornerRadius: 18))
            .overlay(
                RoundedRectangle(cornerRadius: 18)
                    .stroke(Color(red: 0.89, green: 0.91, blue: 0.95), lineWidth: 1)
            )
        }
        .frame(width: 390, alignment: .leading)
        .padding(24)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .overlay(
            RoundedRectangle(cornerRadius: 24)
                .stroke(Color(red: 0.89, green: 0.91, blue: 0.95), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.06), radius: 20, x: 0, y: 8)
    }

    func chip(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Color(red: 0.15, green: 0.39, blue: 0.92))
            .padding(.horizontal, 13)
            .padding(.vertical, 9)
            .background(Color(red: 0.94, green: 0.96, blue: 1.0))
            .clipShape(Capsule())
            .overlay(Capsule().stroke(Color(red: 0.86, green: 0.9, blue: 0.97), lineWidth: 1))
    }
}

@main
struct CSUAutoReloginSetupApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .windowResizability(.contentSize)
    }
}
