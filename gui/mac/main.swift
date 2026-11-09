// 刷课助手 Mac 外壳：启动本地后台 (gui/server.py)，用原生窗口显示界面。
// 编译见 gui/build_app.sh
import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var overlay: NSView!
    private var statusLabel: NSTextField!
    private var spinner: NSProgressIndicator!
    private var server: Process?
    private var port: Int?
    private var quitting = false
    private var quitConfirmed = false
    private var stdoutBuffer = ""
    private var stderrTail = ""
    private let token = UUID().uuidString.replacingOccurrences(of: "-", with: "")

    private var projectPath: String {
        if let p = ProcessInfo.processInfo.environment["CXGUI_PROJECT"], !p.isEmpty { return p }
        if let p = Bundle.main.object(forInfoDictionaryKey: "CXProjectPath") as? String, !p.isEmpty { return p }
        return FileManager.default.currentDirectoryPath
    }

    // MARK: - 生命周期
    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        startServer()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if confirmQuitIfRunning() {
            quitConfirmed = true
            return true
        }
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if !quitConfirmed && !confirmQuitIfRunning() { return .terminateCancel }
        quitting = true
        if let s = server, s.isRunning {
            s.terminate()
            let deadline = Date().addingTimeInterval(6)
            while s.isRunning && Date() < deadline { usleep(100_000) }
            if s.isRunning { kill(s.processIdentifier, SIGKILL) }
        }
        return .terminateNow
    }

    /// 正在学习时询问是否退出；返回 true 表示可以退出
    private func confirmQuitIfRunning() -> Bool {
        guard isTaskRunning() else { return true }
        let alert = NSAlert()
        alert.messageText = "有账号正在学习或排队，确定要退出吗？"
        alert.informativeText = "退出会停止所有账号的学习并取消排队。已完成的进度会保存在学习通，下次可以接着学。"
        alert.addButton(withTitle: "继续学习")
        alert.addButton(withTitle: "停止并退出")
        alert.buttons[1].hasDestructiveAction = true
        return alert.runModal() == .alertSecondButtonReturn
    }

    private func isTaskRunning() -> Bool {
        guard let port = port, let url = URL(string: "http://127.0.0.1:\(port)/api/state") else { return false }
        var req = URLRequest(url: url, timeoutInterval: 2)
        req.setValue(token, forHTTPHeaderField: "X-Token")
        let sem = DispatchSemaphore(value: 0)
        var running = false
        URLSession.shared.dataTask(with: req) { data, _, _ in
            if let data = data,
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let busy = obj["any_busy"] as? Bool {
                running = busy
            }
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 2.5)
        return running
    }

    // MARK: - 界面
    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 800),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "刷课助手"
        window.minSize = NSSize(width: 820, height: 600)
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.center()
        window.setFrameAutosaveName("ShuaKeMainWindow")

        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        webView.isHidden = true

        let root = NSView()
        root.wantsLayer = true
        webView.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(webView)

        overlay = NSView()
        overlay.translatesAutoresizingMaskIntoConstraints = false
        spinner = NSProgressIndicator()
        spinner.style = .spinning
        spinner.controlSize = .regular
        spinner.translatesAutoresizingMaskIntoConstraints = false
        spinner.startAnimation(nil)
        statusLabel = NSTextField(wrappingLabelWithString: "正在启动…")
        statusLabel.alignment = .center
        statusLabel.textColor = .secondaryLabelColor
        statusLabel.isSelectable = true
        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        overlay.addSubview(spinner)
        overlay.addSubview(statusLabel)
        root.addSubview(overlay)

        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            webView.topAnchor.constraint(equalTo: root.topAnchor),
            webView.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            overlay.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            overlay.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            overlay.topAnchor.constraint(equalTo: root.topAnchor),
            overlay.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            spinner.centerXAnchor.constraint(equalTo: overlay.centerXAnchor),
            spinner.centerYAnchor.constraint(equalTo: overlay.centerYAnchor, constant: -16),
            statusLabel.topAnchor.constraint(equalTo: spinner.bottomAnchor, constant: 14),
            statusLabel.centerXAnchor.constraint(equalTo: overlay.centerXAnchor),
            statusLabel.widthAnchor.constraint(lessThanOrEqualToConstant: 560),
        ])
        window.contentView = root
        window.makeKeyAndOrderFront(nil)
    }

    private func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于刷课助手", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        let settings = NSMenuItem(title: "设置…", action: #selector(openSettings), keyEquivalent: ",")
        settings.target = self
        appMenu.addItem(settings)
        let folder = NSMenuItem(title: "打开项目文件夹", action: #selector(openProjectFolder), keyEquivalent: "")
        folder.target = self
        appMenu.addItem(folder)
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "隐藏刷课助手", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "退出刷课助手", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "拷贝", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        let winItem = NSMenuItem()
        let win = NSMenu(title: "窗口")
        win.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        winItem.submenu = win
        main.addItem(winItem)
        NSApp.windowsMenu = win

        NSApp.mainMenu = main
    }

    @objc private func openSettings() {
        webView.evaluateJavaScript("window.cxOpenSettings && window.cxOpenSettings();", completionHandler: nil)
    }

    @objc private func openProjectFolder() {
        NSWorkspace.shared.open(URL(fileURLWithPath: projectPath))
    }

    private func showError(_ text: String) {
        spinner.stopAnimation(nil)
        spinner.isHidden = true
        overlay.isHidden = false
        webView.isHidden = true
        statusLabel.stringValue = text
        statusLabel.textColor = .labelColor
    }

    // MARK: - 后台服务
    private func startServer() {
        let python = projectPath + "/.venv/bin/python"
        let script = projectPath + "/gui/server.py"
        guard FileManager.default.isExecutableFile(atPath: python),
              FileManager.default.fileExists(atPath: script) else {
            showError("找不到项目或 Python 环境：\n\(projectPath)\n\n请确认 chaoxing 项目文件夹没有被移动，并已安装依赖。")
            return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [script]
        p.currentDirectoryURL = URL(fileURLWithPath: projectPath)
        var env = ProcessInfo.processInfo.environment
        env["CXGUI_TOKEN"] = token
        env["CXGUI_WATCH_PARENT"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        p.environment = env

        let out = Pipe(), err = Pipe()
        p.standardOutput = out
        p.standardError = err
        out.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            if data.isEmpty { h.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.handleStdout(String(decoding: data, as: UTF8.self)) }
        }
        err.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            if data.isEmpty { h.readabilityHandler = nil; return }
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.stderrTail = String((self.stderrTail + String(decoding: data, as: UTF8.self)).suffix(1500))
            }
        }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self = self, !self.quitting else { return }
                self.showError("后台服务意外退出（代码 \(proc.terminationStatus)）。\n\n\(self.stderrTail)\n\n请重新打开应用；如果反复出现，可以查看 gui/data/logs/server.log。")
            }
        }
        do {
            try p.run()
            server = p
        } catch {
            showError("启动后台服务失败：\(error.localizedDescription)")
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 40) { [weak self] in
            guard let self = self, self.port == nil, !self.quitting else { return }
            self.showError("后台服务启动超时。\n\n\(self.stderrTail)")
        }
    }

    private func handleStdout(_ chunk: String) {
        stdoutBuffer += chunk
        while let range = stdoutBuffer.range(of: "\n") {
            let line = String(stdoutBuffer[..<range.lowerBound])
            stdoutBuffer.removeSubrange(..<range.upperBound)
            if port == nil, line.hasPrefix("CXGUI_READY "), let p = Int(line.dropFirst(12).trimmingCharacters(in: .whitespaces)) {
                port = p
                statusLabel.stringValue = "正在加载界面…"
                if let url = URL(string: "http://127.0.0.1:\(p)/?t=\(token)") {
                    webView.load(URLRequest(url: url))
                }
            }
        }
    }

    // MARK: - WebView
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.isHidden = false
        overlay.isHidden = true
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        showError("界面加载失败：\(error.localizedDescription)")
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showError("界面加载失败：\(error.localizedDescription)")
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, url.host != "127.0.0.1", url.scheme == "http" || url.scheme == "https" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.runModal()
        completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "确定")
        alert.addButton(withTitle: "取消")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
