import SwiftUI
import Foundation
import AppKit
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

enum ProviderOption: String, CaseIterable, Identifiable {
    case mobile = "@cmccn"
    case unicom = "@unicomn"
    case telecom = "@telecomn"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .mobile:
            return "中国移动"
        case .unicom:
            return "中国联通"
        case .telecom:
            return "中国电信"
        }
    }

    static func fromSuffix(_ suffix: String) -> ProviderOption {
        ProviderOption(rawValue: suffix.trimmingCharacters(in: .whitespacesAndNewlines)) ?? .mobile
    }
}

extension Notification.Name {
    static let managedQuitAttempted = Notification.Name("ManagedQuitAttempted")
}

@MainActor
final class ManagedAppRuntime {
    static let shared = ManagedAppRuntime()

    let windowDelegate = ManagedWindowDelegate()
    var allowTermination = false
    var requiresManagedShutdown = false
    private(set) var launchedInBackground = ProcessInfo.processInfo.arguments.contains("--background")

    private init() {}

    func installWindowDelegate(on window: NSWindow) {
        guard window.delegate !== windowDelegate else {
            return
        }
        window.delegate = windowDelegate
        window.isReleasedWhenClosed = false
    }

    func hideToBackground() {
        for window in NSApp.windows {
            window.orderOut(nil)
        }
        NSApp.hide(nil)
    }

    func reopenMainWindow() {
        for window in NSApp.windows {
            window.makeKeyAndOrderFront(nil)
        }
        NSApp.activate(ignoringOtherApps: true)
    }

    func blockExternalQuitAndReveal() {
        NotificationCenter.default.post(name: .managedQuitAttempted, object: nil)
        reopenMainWindow()
    }

    func completeManagedShutdown() {
        allowTermination = true
        requiresManagedShutdown = false
        NSApp.terminate(nil)
    }

    func consumeBackgroundLaunchFlag() -> Bool {
        let value = launchedInBackground
        launchedInBackground = false
        return value
    }
}

@MainActor
final class ManagedWindowDelegate: NSObject, NSWindowDelegate {
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if !ManagedAppRuntime.shared.requiresManagedShutdown {
            NSApp.terminate(nil)
            return false
        }
        sender.orderOut(nil)
        NSApp.hide(nil)
        return false
    }
}

@MainActor
final class SetupViewModel: ObservableObject {
    let appSupportDir = URL(fileURLWithPath: "/Library/Application Support/CSUStudentWiFi", isDirectory: true)
    let userSupportDir = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/CSUStudentWiFi", isDirectory: true)

    @Published var config = SetupConfig()
    @Published var configPathText = ""
    @Published var statePathText = ""
    @Published var logPathText = ""
    @Published var autoRunText = "未开启"
    @Published var backgroundStateText = "后台未开启"
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

    private var pageStatusOverrideText: String?
    private var pageStatusOverrideTone: StatusTone?
    private var pageStatusOverrideExpiry = Date.distantPast
    private var backgroundProcess: Process?
    private var backgroundRestartWorkItem: DispatchWorkItem?
    private var managedQuitObserver: NSObjectProtocol?
    private var suppressNextBackgroundRestart = false

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

    init() {
        managedQuitObserver = NotificationCenter.default.addObserver(
            forName: .managedQuitAttempted,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.setTransientPageStatus(
                    "后台仍在运行。想彻底停止，请打开窗口后点“关闭后台运行”。",
                    tone: .warn,
                    holdFor: 10
                )
            }
        }
    }

    deinit {
        if let managedQuitObserver {
            NotificationCenter.default.removeObserver(managedQuitObserver)
        }
    }

    var canEnableAutostart: Bool {
        isConfigReady && autoRunText != "已经开启" && !isTesting
    }

    var canRunImmediateTest: Bool {
        isConfigReady && !isTesting
    }

    var canDisableAutostart: Bool {
        autoRunText == "已经开启" && !isTesting
    }

    func loadInitialState() {
        ensureUserConfig()
        loadConfig()
        refreshRuntimeState()
    }

    func refreshRuntimeState(forceRestartRunner: Bool = false) {
        configPathText = configURL.path
        statePathText = stateURL.path
        logPathText = logURL.path
        configStateText = isConfigReady ? "已经可用" : "还没填完整"
        autoRunText = isLaunchAgentLoaded() ? "已经开启" : "还没开启"
        syncBackgroundRunner(forceRestart: forceRestartRunner)
        lastTestText = describeLastTest()
        applyPageStatus()
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
            setTransientPageStatus(
                "配置已保存。下一步点“开启开机自启”后，这个软件会在开机后自动进入后台运行。",
                tone: .good
            )
            refreshRuntimeState(forceRestartRunner: true)
        } catch {
            setTransientPageStatus("保存失败：\(error.localizedDescription)", tone: .bad, holdFor: 12)
        }
    }

    func enableAutostart() {
        runAuxiliaryCommand(
            executable: setupScriptURL,
            arguments: ["--load-if-ready"],
            successPrefix: "开机自启和后台运行已开启",
            forceRestartRunner: true
        )
    }

    func disableAutostart() {
        runAuxiliaryCommand(
            executable: disableScriptURL,
            arguments: [],
            successPrefix: "后台运行已关闭",
            terminateAppAfterSuccess: true
        )
    }

    func openConfigFile() {
        NSWorkspace.shared.open(configURL)
    }

    func openLogFile() {
        NSWorkspace.shared.open(logURL)
    }

    func revealSupportFolder() {
        NSWorkspace.shared.activateFileViewerSelecting([userSupportDir])
    }

    func runImmediateTest() {
        if isTesting {
            setTransientPageStatus("已经有一个测试在运行，请稍等。", tone: .warn)
            return
        }
        if !isConfigReady {
            setTransientPageStatus("配置还没填完整。现在默认只需要账号和密码。", tone: .warn)
            return
        }
        isTesting = true
        lastStartedAt = timestampNow()
        testStatus = "测试中：\(lastStartedAt)"
        testStatusTone = .normal
        lastRunOutput = ""
        testOutput = "正在执行真实重新登录，请稍等..."
        setTransientPageStatus(
            "正在执行一次真实的强制重登录。测试期间如果你原本在线，出现几秒短暂断网属于正常现象。",
            tone: .normal,
            holdFor: 3600
        )

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
                let summary: String
                let tone: StatusTone
                if result.exitCode == 0 {
                    summary = "真实测试已完成。最近一次重登录链路执行成功。"
                    tone = .good
                } else if result.exitCode == 3 {
                    summary = "真实测试已完成，但本次流程被跳过了。可以检查当前网络环境后再试一次。"
                    tone = .warn
                } else {
                    summary = "真实测试失败（exit=\(result.exitCode)）。可以先查看本次输出和最近日志。"
                    tone = .bad
                }
                self.setTransientPageStatus(summary, tone: tone, holdFor: 12)
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

    private func runAuxiliaryCommand(
        executable: URL,
        arguments: [String],
        successPrefix: String,
        forceRestartRunner: Bool = false,
        terminateAppAfterSuccess: Bool = false
    ) {
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Self.runProcess(executable: executable, arguments: arguments)
            DispatchQueue.main.async {
                if result.exitCode == 0 {
                    self.setTransientPageStatus(
                        "\(successPrefix)\n\n\(result.output.isEmpty ? "完成" : result.output)",
                        tone: .good
                    )
                    if terminateAppAfterSuccess {
                        self.stopBackgroundRunner()
                        ManagedAppRuntime.shared.completeManagedShutdown()
                        return
                    }
                } else {
                    self.setTransientPageStatus(
                        "\(successPrefix)失败：\(result.output.isEmpty ? "exit=\(result.exitCode)" : result.output)",
                        tone: .bad,
                        holdFor: 12
                    )
                }
                self.refreshRuntimeState(forceRestartRunner: forceRestartRunner)
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

    private func currentRecommendation() -> String {
        if !isConfigReady {
            return "填好账号、密码和运营商后保存。"
        }
        if isTesting {
            return "正在执行真实测试。"
        }
        if autoRunText == "已经开启" && backgroundProcess?.isRunning == true {
            return "后台已经常驻运行。点左上角关闭只会缩到后台，想停用请点“关闭后台运行”。"
        }
        if autoRunText == "已经开启" {
            return "开机自启已经打开，后台检查进程正在准备启动。"
        }
        return "配置已保存后，再点“开启开机自启”即可。"
    }

    private func currentRecommendationTone() -> StatusTone {
        if isTesting {
            return .normal
        }
        if !isConfigReady {
            return .warn
        }
        if autoRunText == "已经开启" {
            return .good
        }
        return .normal
    }

    private func currentLogChunk() -> String {
        let tail = tailText(logURL, limit: 80)
        return tail.isEmpty ? "" : "[最近日志]\n\(tail)"
    }

    private func syncBackgroundRunner(forceRestart: Bool) {
        ManagedAppRuntime.shared.requiresManagedShutdown = (autoRunText == "已经开启")

        if forceRestart {
            stopBackgroundRunner()
        }

        if autoRunText == "已经开启" && isConfigReady {
            startBackgroundRunnerIfNeeded()
        } else {
            stopBackgroundRunner()
        }

        if backgroundProcess?.isRunning == true {
            backgroundStateText = "后台运行中"
        } else if autoRunText == "已经开启" {
            backgroundStateText = "后台启动中"
        } else {
            backgroundStateText = "后台未开启"
        }
    }

    private func startBackgroundRunnerIfNeeded() {
        guard backgroundProcess?.isRunning != true else {
            return
        }
        guard FileManager.default.isExecutableFile(atPath: runnerURL.path) else {
            setTransientPageStatus("后台检查组件不存在，请重新安装应用。", tone: .bad, holdFor: 12)
            backgroundStateText = "后台缺失"
            return
        }

        backgroundRestartWorkItem?.cancel()

        let process = Process()
        process.executableURL = runnerURL
        process.arguments = ["--config", configURL.path, "--verbose"]

        if let devNull = FileHandle(forWritingAtPath: "/dev/null") {
            process.standardOutput = devNull
            process.standardError = devNull
        }

        process.terminationHandler = { [weak self] terminatedProcess in
            DispatchQueue.main.async {
                self?.handleBackgroundRunnerTermination(exitCode: terminatedProcess.terminationStatus)
            }
        }

        do {
            try process.run()
            backgroundProcess = process
            backgroundStateText = "后台运行中"
        } catch {
            backgroundProcess = nil
            backgroundStateText = "后台启动失败"
            setTransientPageStatus("后台检查进程启动失败：\(error.localizedDescription)", tone: .bad, holdFor: 12)
        }
    }

    private func stopBackgroundRunner() {
        backgroundRestartWorkItem?.cancel()
        backgroundRestartWorkItem = nil

        guard let process = backgroundProcess else {
            return
        }

        if process.isRunning {
            suppressNextBackgroundRestart = true
            process.terminate()
        }
        backgroundProcess = nil
    }

    private func handleBackgroundRunnerTermination(exitCode: Int32) {
        backgroundProcess = nil

        if suppressNextBackgroundRestart {
            suppressNextBackgroundRestart = false
            if autoRunText == "已经开启" {
                backgroundStateText = "后台启动中"
            } else {
                backgroundStateText = "后台未开启"
            }
            return
        }

        let shouldRestart = autoRunText == "已经开启" && isConfigReady
        if !shouldRestart {
            backgroundStateText = "后台未开启"
            return
        }

        backgroundStateText = "后台重启中"
        let workItem = DispatchWorkItem { [weak self] in
            self?.startBackgroundRunnerIfNeeded()
            self?.refreshRuntimeState()
        }
        backgroundRestartWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + 2, execute: workItem)

        if exitCode != 0 && exitCode != 15 {
            setTransientPageStatus(
                "后台检查进程意外退出（exit=\(exitCode)），正在自动拉起。",
                tone: .warn,
                holdFor: 10
            )
        }
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

    private func applyPageStatus() {
        if
            let overrideText = pageStatusOverrideText,
            let overrideTone = pageStatusOverrideTone,
            pageStatusOverrideExpiry > Date()
        {
            pageStatus = overrideText
            pageStatusTone = overrideTone
            return
        }
        clearTransientPageStatus()
        pageStatus = currentRecommendation()
        pageStatusTone = currentRecommendationTone()
    }

    private func setTransientPageStatus(_ text: String, tone: StatusTone, holdFor seconds: TimeInterval = 8) {
        pageStatusOverrideText = text
        pageStatusOverrideTone = tone
        pageStatusOverrideExpiry = Date().addingTimeInterval(seconds)
        pageStatus = text
        pageStatusTone = tone
    }

    private func clearTransientPageStatus() {
        pageStatusOverrideText = nil
        pageStatusOverrideTone = nil
        pageStatusOverrideExpiry = .distantPast
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

enum Theme {
    static let backgroundTop = Color(red: 0.96, green: 0.97, blue: 0.995)
    static let backgroundBottom = Color(red: 0.93, green: 0.95, blue: 0.985)
    static let sidebarTop = Color(red: 0.985, green: 0.989, blue: 1.0)
    static let sidebarBottom = Color(red: 0.944, green: 0.958, blue: 0.992)
    static let panel = Color.white
    static let panelSoft = Color(red: 0.973, green: 0.978, blue: 0.989)
    static let border = Color(red: 0.87, green: 0.9, blue: 0.95)
    static let ink = Color(red: 0.13, green: 0.17, blue: 0.25)
    static let subtext = Color(red: 0.41, green: 0.47, blue: 0.58)
    static let blue = Color(red: 0.25, green: 0.43, blue: 0.9)
    static let blueSoft = Color(red: 0.92, green: 0.95, blue: 1.0)
    static let orange = Color(red: 0.95, green: 0.65, blue: 0.25)
    static let mint = Color(red: 0.2, green: 0.63, blue: 0.46)
    static let rose = Color(red: 0.83, green: 0.35, blue: 0.34)
}

struct BrandMark: View {
    let size: CGFloat

    init(size: CGFloat = 72) {
        self.size = size
    }

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.29, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            Color(red: 0.98, green: 0.99, blue: 1.0),
                            Color(red: 0.82, green: 0.89, blue: 1.0),
                            Color(red: 0.98, green: 0.89, blue: 0.77),
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
            RoundedRectangle(cornerRadius: size * 0.23, style: .continuous)
                .fill(Color.white.opacity(0.92))
                .padding(size * 0.09)
            Image(systemName: "wifi")
                .font(.system(size: size * 0.34, weight: .semibold))
                .foregroundStyle(Theme.ink)
                .offset(y: -size * 0.045)
            Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                .font(.system(size: size * 0.22, weight: .semibold))
                .foregroundStyle(Theme.orange)
                .offset(x: size * 0.17, y: size * 0.18)
        }
        .frame(width: size, height: size)
        .shadow(color: Color.black.opacity(0.08), radius: 18, x: 0, y: 10)
    }
}

struct InstallerCard<Content: View>: View {
    let title: String
    let subtitle: String?
    let content: Content

    init(title: String, subtitle: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.subtitle = subtitle
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(Theme.ink)
                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: 14))
                        .foregroundStyle(Theme.subtext)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            content
        }
        .padding(22)
        .background(Theme.panel)
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.04), radius: 18, x: 0, y: 10)
    }
}

struct ToneBanner: View {
    let text: String
    let tone: StatusTone

    var palette: (background: Color, border: Color, text: Color, icon: String) {
        switch tone {
        case .good:
            return (
                Color(red: 0.94, green: 0.99, blue: 0.96),
                Color(red: 0.82, green: 0.93, blue: 0.86),
                Theme.mint,
                "checkmark.circle.fill"
            )
        case .warn:
            return (
                Color(red: 1.0, green: 0.97, blue: 0.92),
                Color(red: 0.96, green: 0.86, blue: 0.7),
                Color(red: 0.63, green: 0.4, blue: 0.11),
                "exclamationmark.circle.fill"
            )
        case .bad:
            return (
                Color(red: 0.99, green: 0.95, blue: 0.95),
                Color(red: 0.96, green: 0.83, blue: 0.83),
                Theme.rose,
                "xmark.circle.fill"
            )
        case .normal:
            return (
                Theme.blueSoft,
                Color(red: 0.82, green: 0.88, blue: 0.97),
                Theme.blue,
                "bolt.circle.fill"
            )
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: palette.icon)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(palette.text)
                .padding(.top, 1)
            Text(text)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(palette.text)
                .lineSpacing(3)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(15)
        .background(palette.background)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(palette.border, lineWidth: 1)
        )
    }
}

struct StepRow: View {
    let number: String
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Text(number)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Theme.blue)
                .frame(width: 30, height: 30)
                .background(Theme.blueSoft)
                .clipShape(Circle())
                .overlay(Circle().stroke(Theme.border, lineWidth: 1))
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                Text(detail)
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.subtext)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
    }
}

struct StatusPill: View {
    let title: String
    let value: String
    let tone: StatusTone

    var accent: Color {
        switch tone {
        case .good:
            return Theme.mint
        case .warn:
            return Theme.orange
        case .bad:
            return Theme.rose
        case .normal:
            return Theme.blue
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Circle()
                    .fill(accent)
                    .frame(width: 8, height: 8)
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.subtext)
            }
            Text(value)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(Theme.ink)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(16)
        .background(Theme.panelSoft)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }
}

struct StrategyRow: View {
    let icon: String
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Theme.blue)
                .frame(width: 34, height: 34)
                .background(Theme.blueSoft)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                Text(detail)
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.subtext)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
    }
}

struct InputField<Content: View>: View {
    let title: String
    let caption: String?
    let content: Content

    init(title: String, caption: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.caption = caption
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Theme.ink)
            content
            if let caption {
                Text(caption)
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.subtext)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ReadOnlyField: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Theme.ink)
            Text(value)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Theme.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(Theme.panelSoft)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(Theme.border, lineWidth: 1)
                )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct PathRow: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Theme.subtext)
            Text(value)
                .font(.system(size: 12, weight: .medium, design: .monospaced))
                .foregroundStyle(Theme.ink)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 3)
    }
}

struct HeroBadge: View {
    let icon: String
    let text: String

    var body: some View {
        Label(text, systemImage: icon)
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(Theme.blue)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color.white.opacity(0.76))
            .clipShape(Capsule())
            .overlay(
                Capsule()
                    .stroke(Theme.border.opacity(0.9), lineWidth: 1)
            )
    }
}

struct ProgressRing: View {
    let progress: Double
    let label: String
    let caption: String
    let tone: StatusTone
    let size: CGFloat

    init(progress: Double, label: String, caption: String, tone: StatusTone, size: CGFloat = 116) {
        self.progress = progress
        self.label = label
        self.caption = caption
        self.tone = tone
        self.size = size
    }

    private var accent: Color {
        switch tone {
        case .good:
            return Theme.mint
        case .warn:
            return Theme.orange
        case .bad:
            return Theme.rose
        case .normal:
            return Theme.blue
        }
    }

    private var clampedProgress: CGFloat {
        CGFloat(min(max(progress, 0.04), 1.0))
    }

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.white.opacity(0.45), lineWidth: size * 0.1)
            Circle()
                .trim(from: 0, to: clampedProgress)
                .stroke(
                    accent,
                    style: StrokeStyle(lineWidth: size * 0.1, lineCap: .round)
                )
                .rotationEffect(.degrees(-90))
            VStack(spacing: 4) {
                Text(label)
                    .font(.system(size: size * 0.19, weight: .bold))
                    .foregroundStyle(Theme.ink)
                Text(caption)
                    .font(.system(size: size * 0.095, weight: .semibold))
                    .foregroundStyle(Theme.subtext)
            }
        }
        .frame(width: size, height: size)
    }
}

struct MiniStatRow: View {
    let icon: String
    let title: String
    let value: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Theme.blue)
                .frame(width: 32, height: 32)
                .background(Theme.blueSoft)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.subtext)
                Text(value)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
    }
}

struct QuickAccessButton: View {
    let icon: String
    let title: String
    let detail: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(alignment: .center, spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Theme.blue)
                    .frame(width: 38, height: 38)
                    .background(Theme.blueSoft)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Theme.ink)
                    Text(detail)
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.subtext)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Image(systemName: "arrow.right")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Theme.subtext)
            }
            .padding(14)
            .background(Theme.panelSoft)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(Theme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

struct SettingsGroup<Content: View>: View {
    let icon: String
    let title: String
    let subtitle: String?
    let content: Content

    init(icon: String, title: String, subtitle: String? = nil, @ViewBuilder content: () -> Content) {
        self.icon = icon
        self.title = title
        self.subtitle = subtitle
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Theme.blue)
                    .frame(width: 36, height: 36)
                    .background(Color.white.opacity(0.78))
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Theme.ink)
                    if let subtitle {
                        Text(subtitle)
                            .font(.system(size: 12))
                            .foregroundStyle(Theme.subtext)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            content
        }
        .padding(18)
        .background(Theme.panelSoft)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Theme.border, lineWidth: 1)
        )
    }
}

struct WindowAccessor: NSViewRepresentable {
    let onResolve: (NSWindow) -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            if let window = view.window {
                onResolve(window)
            }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            if let window = nsView.window {
                onResolve(window)
            }
        }
    }
}

extension View {
    func installerInputStyle() -> some View {
        self
            .textFieldStyle(.plain)
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(Theme.ink)
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(Color.white.opacity(0.94))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(Theme.border, lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(0.02), radius: 6, x: 0, y: 3)
    }
}

struct ContentView: View {
    @StateObject private var model = SetupViewModel()
    @State private var showPassword = false
    private let timer = Timer.publish(every: 3.0, on: .main, in: .common).autoconnect()

    var passwordEntryWarning: String? {
        let password = model.config.password
        let suspiciousPunctuation: [(String, String)] = [
            ("。", "."),
            ("，", ","),
            ("；", ";"),
            ("：", ":"),
        ]
        for (wide, ascii) in suspiciousPunctuation where password.contains(wide) {
            return "当前密码里包含全角符号“\(wide)”，如果你本来想输入英文“\(ascii)”请改回半角字符。"
        }
        return nil
    }

    var providerSelection: Binding<ProviderOption> {
        Binding(
            get: { ProviderOption.fromSuffix(model.config.accountSuffix) },
            set: { model.config.accountSuffix = $0.rawValue }
        )
    }

    var backgroundStatusText: String {
        model.backgroundStateText
    }

    var runningBehaviorHint: String {
        "开启后会开机自动启动。点左上角关闭只会缩到后台，想彻底停止必须重新打开软件点“关闭后台运行”。"
    }

    var body: some View {
        GeometryReader { proxy in
            let detailWidth = proxy.size.width

            ZStack {
                backgroundArt

                detailPane(width: detailWidth)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            }
        }
        .frame(minWidth: 980, minHeight: 760)
        .onAppear {
            model.loadInitialState()
            if ManagedAppRuntime.shared.consumeBackgroundLaunchFlag() {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                    ManagedAppRuntime.shared.hideToBackground()
                }
            }
        }
        .onReceive(timer) { _ in
            model.refreshRuntimeState()
        }
        .animation(.easeInOut(duration: 0.22), value: model.isTesting)
        .background(
            WindowAccessor { window in
                ManagedAppRuntime.shared.installWindowDelegate(on: window)
            }
        )
    }

    var backgroundArt: some View {
        ZStack {
            LinearGradient(
                colors: [Theme.backgroundTop, Theme.backgroundBottom],
                startPoint: .top,
                endPoint: .bottom
            )

            Circle()
                .fill(Color.white.opacity(0.75))
                .frame(width: 460, height: 460)
                .blur(radius: 110)
                .offset(x: -260, y: -260)

            Circle()
                .fill(Theme.blue.opacity(0.15))
                .frame(width: 340, height: 340)
                .blur(radius: 84)
                .offset(x: 430, y: -220)

            Circle()
                .fill(Theme.orange.opacity(0.12))
                .frame(width: 420, height: 420)
                .blur(radius: 96)
                .offset(x: 380, y: 260)
        }
        .ignoresSafeArea()
    }

    func detailPane(width: CGFloat) -> some View {
        let contentWidth = min(max(width - 72, 0), 760)

        return VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    headerSection(width: contentWidth)

                    Divider()

                    VStack(alignment: .leading, spacing: 16) {
                        Text("账号登录")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Theme.ink)

                        LazyVGrid(columns: formGridColumns(for: contentWidth), alignment: .leading, spacing: 16) {
                            InputField(title: "校园网账号") {
                                TextField("例如 8208231325", text: $model.config.username)
                                    .installerInputStyle()
                            }
                            InputField(title: "校园网密码") {
                                HStack(spacing: 10) {
                                    Group {
                                        if showPassword {
                                            TextField("输入真实密码", text: $model.config.password)
                                        } else {
                                            SecureField("输入真实密码", text: $model.config.password)
                                        }
                                    }
                                    .installerInputStyle()

                                    Button {
                                        showPassword.toggle()
                                    } label: {
                                        Image(systemName: showPassword ? "eye.slash" : "eye")
                                            .font(.system(size: 15, weight: .semibold))
                                            .foregroundStyle(Theme.blue)
                                            .frame(width: 42, height: 42)
                                            .background(Color.white.opacity(0.94))
                                            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                                            .overlay(
                                                RoundedRectangle(cornerRadius: 14, style: .continuous)
                                                    .stroke(Theme.border, lineWidth: 1)
                                            )
                                    }
                                    .buttonStyle(.plain)
                                    .help(showPassword ? "隐藏密码" : "显示密码")
                                }
                            }
                        }

                        InputField(title: "运营商") {
                            Picker("运营商", selection: providerSelection) {
                                ForEach(ProviderOption.allCases) { provider in
                                    Text(provider.title)
                                        .tag(provider)
                                }
                            }
                            .pickerStyle(.segmented)
                        }

                        if let passwordEntryWarning = passwordEntryWarning {
                            ToneBanner(text: passwordEntryWarning, tone: .warn)
                        }

                        Text(runningBehaviorHint)
                            .font(.system(size: 13))
                            .foregroundStyle(Theme.subtext)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(32)
                .frame(maxWidth: contentWidth, alignment: .leading)
                .frame(maxWidth: .infinity)
                .padding(.top, 8)
            }

            Divider()

            footerBar()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    func headerSection(width: CGFloat) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: 22) {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 14) {
                        BrandMark(size: 72)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("CSU Student Wi-Fi")
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(Theme.blue)
                            Text("校园网后台登录")
                                .font(.system(size: 30, weight: .bold))
                                .foregroundStyle(Theme.ink)
                        }
                    }
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 10) {
                            HeroBadge(icon: "power", text: backgroundStatusText)
                            HeroBadge(icon: "at", text: providerSelection.wrappedValue.title)
                            HeroBadge(icon: "checkmark.shield", text: "关闭窗口继续后台运行")
                        }
                        VStack(alignment: .leading, spacing: 10) {
                            HeroBadge(icon: "power", text: backgroundStatusText)
                            HeroBadge(icon: "at", text: providerSelection.wrappedValue.title)
                            HeroBadge(icon: "checkmark.shield", text: "关闭窗口继续后台运行")
                        }
                    }
                }
                Spacer(minLength: 20)
                Image(systemName: model.backgroundStateText == "后台运行中" ? "power.circle.fill" : "pause.circle.fill")
                    .font(.system(size: 40, weight: .semibold))
                    .foregroundStyle(model.backgroundStateText == "后台运行中" ? Theme.mint : Theme.orange)
                    .frame(width: 78, height: 78)
                    .background(Color.white.opacity(0.88))
                    .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(Theme.border, lineWidth: 1)
                    )
                    .shadow(color: Color.black.opacity(0.04), radius: 12, x: 0, y: 6)
            }

            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 14) {
                    BrandMark(size: 68)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("CSU Student Wi-Fi")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(Theme.blue)
                        Text("校园网后台登录")
                            .font(.system(size: 30, weight: .bold))
                            .foregroundStyle(Theme.ink)
                    }
                }
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 10) {
                        HeroBadge(icon: "power", text: backgroundStatusText)
                        HeroBadge(icon: "at", text: providerSelection.wrappedValue.title)
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        HeroBadge(icon: "power", text: backgroundStatusText)
                        HeroBadge(icon: "at", text: providerSelection.wrappedValue.title)
                    }
                }
                Text(runningBehaviorHint)
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.subtext)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    func footerBar() -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: 14) {
                footerSummary
                Spacer(minLength: 20)
                footerButtons
            }

            VStack(alignment: .leading, spacing: 14) {
                footerSummary
                footerButtons
            }
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 18)
    }

    var footerSummary: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(model.pageStatus)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Theme.ink)
                .lineLimit(3)
        }
    }

    var footerButtons: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 10) {
                saveButton
                enableButton
                disableButton
            }

            VStack(alignment: .leading, spacing: 10) {
                saveButton
                HStack(spacing: 10) {
                    enableButton
                    disableButton
                }
            }
        }
    }

    var saveButton: some View {
        Button {
            model.saveConfig()
        } label: {
            Label("保存配置", systemImage: "square.and.arrow.down")
        }
        .buttonStyle(.bordered)
        .controlSize(.large)
    }

    var enableButton: some View {
        Button {
            model.enableAutostart()
        } label: {
            Label("开启开机自启", systemImage: "play.fill")
        }
        .buttonStyle(.borderedProminent)
        .tint(Theme.blue)
        .controlSize(.large)
        .disabled(!model.canEnableAutostart)
    }

    var disableButton: some View {
        Button {
            model.disableAutostart()
        } label: {
            Label("关闭后台运行", systemImage: "power.circle")
        }
        .buttonStyle(.borderedProminent)
        .tint(Theme.rose)
        .controlSize(.large)
        .disabled(!model.canDisableAutostart)
    }

    func formGridColumns(for width: CGFloat) -> [GridItem] {
        if width > 820 {
            return Array(repeating: GridItem(.flexible(), spacing: 16, alignment: .top), count: 2)
        }
        return [GridItem(.flexible(), spacing: 16, alignment: .top)]
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if ManagedAppRuntime.shared.allowTermination || !ManagedAppRuntime.shared.requiresManagedShutdown {
            return .terminateNow
        }
        ManagedAppRuntime.shared.blockExternalQuitAndReveal()
        return .terminateCancel
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        ManagedAppRuntime.shared.reopenMainWindow()
        return true
    }
}

@main
struct CSUAutoReloginSetupApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("CSU Student Wi-Fi") {
            ContentView()
        }
        .windowResizability(.automatic)
    }
}
