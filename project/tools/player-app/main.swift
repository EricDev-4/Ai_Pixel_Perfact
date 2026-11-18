// Sprite Player: native macOS window around sprite-player.html (WKWebView, no dependencies).
import Cocoa
import UniformTypeIdentifiers
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var pending: [URL] = []  // files from Dock / Open With, held until the page has loaded
    var pageReady = false

    func applicationDidFinishLaunching(_ note: Notification) {
        web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.uiDelegate = self
        web.navigationDelegate = self
        let html = Bundle.main.url(forResource: "sprite-player", withExtension: "html")!
        web.loadFileURL(html, allowingReadAccessTo: html.deletingLastPathComponent())
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 720),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Sprite Player"
        window.contentView = web
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    // Dock icon drop and Finder "Open With".
    func application(_ application: NSApplication, open urls: [URL]) {
        pending += urls
        flush()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        pageReady = true
        flush()
    }

    // Hand the files to the page as data: URLs (the page cannot read file paths itself).
    func flush() {
        guard pageReady, !pending.isEmpty else { return }
        let mime = ["gif": "image/gif", "webp": "image/webp"]
        let items: [[String: String]] = pending.compactMap { url in
            guard let data = try? Data(contentsOf: url) else { return nil }
            let type = mime[url.pathExtension.lowercased()] ?? "image/png"
            return ["name": url.lastPathComponent, "src": "data:\(type);base64,\(data.base64EncodedString())"]
        }
        pending = []
        guard let json = try? JSONSerialization.data(withJSONObject: items),
              let arg = String(data: json, encoding: .utf8) else { return }
        web.evaluateJavaScript("loadDataURLs(\(arg))")
        window.makeKeyAndOrderFront(nil)
    }

    // <input type=file> needs a native open panel inside WKWebView.
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.allowedContentTypes = [.png, .gif, .webP]
        panel.begin { completionHandler($0 == .OK ? panel.urls : nil) }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)

// Minimal menu so Cmd+Q / Cmd+W work.
let mainMenu = NSMenu()
let appItem = NSMenuItem()
mainMenu.addItem(appItem)
let appMenu = NSMenu()
appMenu.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
appMenu.addItem(withTitle: "Quit Sprite Player", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
appItem.submenu = appMenu
app.mainMenu = mainMenu
app.run()
