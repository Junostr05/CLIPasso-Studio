import Foundation
import Observation
import StudioCore
import Synchronization

#if canImport(Darwin)
    import Darwin
#endif
#if canImport(ImageIO)
    import ImageIO
#endif

/// Where the phone remote's secrets live: the Keychain in the app, memory in tests. Never settings.json, a log, a
/// backup or a diagnosis.
public protocol RemoteSecretStore: Sendable {
    func get(_ name: String) -> String?
    func set(_ name: String, _ value: String)
}

public nonisolated final class MemorySecrets: RemoteSecretStore {
    private let values = Mutex<[String: String]>([:])
    public init() {}
    public func get(_ name: String) -> String? { values.withLock { $0[name] } }
    public func set(_ name: String, _ value: String) { values.withLock { $0[name] = value } }
}

#if canImport(Security)
    import Security

    /// The Keychain: generic passwords of the app's own service.
    public nonisolated final class KeychainSecrets: RemoteSecretStore {
        let service: String

        public init(service: String = "de.junostr05.clipasso-studio.remote") {
            self.service = service
        }

        public func get(_ name: String) -> String? {
            let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                        kSecAttrAccount as String: name, kSecReturnData as String: true,
                                        kSecMatchLimit as String: kSecMatchLimitOne]
            var item: CFTypeRef?
            guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else {
                return nil
            }
            return String(data: data, encoding: .utf8)
        }

        public func set(_ name: String, _ value: String) {
            let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                        kSecAttrAccount as String: name]
            let data = Data(value.utf8)
            if SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary) == errSecItemNotFound {
                var add = query
                add[kSecValueData as String] = data
                add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
                SecItemAdd(add as CFDictionary, nil)
            }
        }
    }
#endif

/// The access code and the PIN (remote.token, remote.pin: made when first needed) and whether the tailnet may
/// connect – read by the server from its own threads.
public nonisolated final class RemoteKeys: Sendable {
    let store: any RemoteSecretStore
    private let tailnet = Mutex(true)

    public init(store: any RemoteSecretStore) {
        self.store = store
    }

    public func token() -> String {
        if let t = store.get("remote_token"), t.count >= 16 { return t }
        let t = RemoteAccess.newToken()
        store.set("remote_token", t)
        return t
    }

    public func pin() -> String {
        if let p = store.get("remote_pin"), RemoteAccess.validPin(p) { return p }
        let p = RemoteAccess.newPin()
        store.set("remote_pin", p)
        return p
    }

    /// Neuer Zugangscode: phones that knew the old one need the new QR code.
    public func newToken() {
        store.set("remote_token", RemoteAccess.newToken())
    }

    /// Neue PIN.
    @discardableResult
    public func newPin() -> String {
        let p = RemoteAccess.newPin()
        store.set("remote_pin", p)
        return p
    }

    /// A PIN of the user's own (six digits; anything else: the PIN stays).
    @discardableResult
    public func setPin(_ text: String) -> Bool {
        let p = text.trimmingCharacters(in: .whitespaces)
        guard RemoteAccess.validPin(p) else { return false }
        store.set("remote_pin", p)
        return true
    }

    public var tailscale: Bool {
        get { tailnet.withLock { $0 } }
        set { tailnet.withLock { $0 = newValue } }
    }

    var secrets: RemoteSecrets {
        RemoteSecrets(token: { [self] in token() }, pin: { [self] in pin() }, tailscale: { [self] in tailscale })
    }
}

/// The phone remote of the app (PhoneLink): on or off and on which port as the settings say, its address and QR code
/// for the settings, and what went wrong (a port in use).
@Observable
public final class PhoneRemote {
    public private(set) var running = false
    public private(set) var port = 0
    /// why it does not run (ui.phone.port_busy), "" when fine
    public private(set) var error = ""
    /// counts new codes and PINs (the settings show them again)
    public private(set) var revision = 0
    @ObservationIgnored public let keys: RemoteKeys
    @ObservationIgnored var server: RemoteServer?

    public init(store: any RemoteSecretStore) {
        keys = RemoteKeys(store: store)
    }

    public func newToken() {
        keys.newToken()
        revision += 1
    }

    @discardableResult
    public func newPin() -> String {
        defer { revision += 1 }
        return keys.newPin()
    }

    @discardableResult
    public func setPin(_ text: String) -> Bool {
        defer { revision += 1 }
        return keys.setPin(text)
    }

    /// remote.url: the address with the access code (the QR code's – it signs in at once).
    public func url(address: String? = nil) -> String {
        "http://\(address ?? Self.localAddress()):\(port)/?t=\(keys.token())"
    }

    /// The same address without the code (to bookmark; then the PIN).
    public func fixedURL(address: String? = nil) -> String {
        "http://\(address ?? Self.localAddress()):\(port)/"
    }

    func started(_ server: RemoteServer, port: Int) {
        self.server = server
        self.port = port
        running = true
        error = ""
    }

    func stopped(error: String = "") {
        server = nil
        running = false
        self.error = error
    }

    /// Something a page shows has changed: the listening pages ask again.
    public func changed() {
        guard let server else { return }
        Task { await server.router.events.changed() }
    }

    /// _eta: the seconds left as "m:ss" or "h:mm:ss" ("" when unknown).
    public nonisolated static func eta(_ seconds: Double?) -> String {
        guard let seconds, seconds.isFinite else { return "" }
        let s = max(0, Int(seconds))
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
            : String(format: "%d:%02d", s / 60, s % 60)
    }

    /// _is_picture: a picture the app can open (HEIC from an iPhone, too).
    public nonisolated static func isPicture(_ file: URL) -> Bool {
        #if canImport(ImageIO)
            guard let source = CGImageSourceCreateWithURL(file as CFURL, nil), CGImageSourceGetCount(source) > 0
            else { return false }
            return CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 64,
            ] as CFDictionary) != nil
        #else
            return false
        #endif
    }

    // MARK: - addresses

    /// local_address: this computer's address in the home network (no packet is sent).
    public nonisolated static func localAddress() -> String {
        #if canImport(Darwin)
            let fd = socket(AF_INET, SOCK_DGRAM, 0)
            if fd >= 0 {
                defer { close(fd) }
                var target = sockaddr_in()
                target.sin_family = sa_family_t(AF_INET)
                target.sin_port = UInt16(9).bigEndian
                inet_pton(AF_INET, "192.0.2.1", &target.sin_addr)  // (TEST-NET: only picks the outgoing interface)
                let connected = withUnsafePointer(to: &target) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                        connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
                var own = sockaddr_in()
                var length = socklen_t(MemoryLayout<sockaddr_in>.size)
                let named = withUnsafeMutablePointer(to: &own) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &length) }
                }
                if connected == 0, named == 0 {
                    var text = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
                    var address = own.sin_addr
                    if inet_ntop(AF_INET, &address, &text, socklen_t(INET_ADDRSTRLEN)) != nil {
                        let ip = String(decoding: text.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }, as: UTF8.self)
                        if !ip.hasPrefix("0.") { return ip }
                    }
                }
            }
        #endif
        return "127.0.0.1"
    }

    /// tailscale_address: this computer's address in a tailnet (100.64.0.0/10), "" when Tailscale does not run here.
    public nonisolated static func tailscaleAddress() -> String {
        #if canImport(Darwin)
            var list: UnsafeMutablePointer<ifaddrs>?
            guard getifaddrs(&list) == 0 else { return "" }
            defer { freeifaddrs(list) }
            var at = list
            while let entry = at {
                defer { at = entry.pointee.ifa_next }
                let flags = Int32(entry.pointee.ifa_flags)
                guard flags & IFF_UP != 0, flags & IFF_RUNNING != 0, let addr = entry.pointee.ifa_addr,
                      addr.pointee.sa_family == sa_family_t(AF_INET)
                else { continue }
                let v4 = addr.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { $0.pointee.sin_addr.s_addr }
                let bytes = withUnsafeBytes(of: v4) { Array($0) }  // (network order)
                if bytes[0] == 100, bytes[1] & 0xC0 == 64 {
                    return bytes.map(String.init).joined(separator: ".")
                }
            }
        #endif
        return ""
    }
}

/// The app behind the phone page (RemoteBridge with PhoneApi): the server asks the app on the main actor.
public nonisolated final class AppRemoteBridge: RemoteApp {
    nonisolated(unsafe) weak var model: AppModel?

    init(model: AppModel) {
        self.model = model
    }

    public func answer(_ action: String, _ data: JSONObject, payload: Data?) async throws -> RemoteAnswer {
        guard let model else { return .json(["ok": false, "error": "the studio is not connected"]) }
        return await model.phoneAnswer(action, data, payload: payload)
    }

    public func status() async -> JSONObject {
        await model?.phoneStatus() ?? [:]
    }

    public func preview() async -> String {
        await model?.phonePreview() ?? ""
    }

    public func texts() async -> JSONObject {
        await model?.phoneTexts() ?? ["lang": "en"]
    }

    public func command(_ name: String) async {
        await model?.phoneCommand(name)
    }

    public func upload(_ file: URL, method: String) async {
        await model?.phoneUpload(file, method: method)
    }

    public func isPicture(_ file: URL) -> Bool {
        PhoneRemote.isPicture(file)
    }
}

public extension AppModel {
    /// The phone remote's secrets: the Keychain (memory where there is none).
    nonisolated static func defaultSecrets() -> any RemoteSecretStore {
        #if canImport(Security)
            KeychainSecrets()
        #else
            MemorySecrets()
        #endif
    }

    /// The phone page's texts (PhoneLink.retranslate): ui.phone.page.* without the prefix, the brush styles, the
    /// papers, the detail brush, the export's options, the methods' names, the language.
    func phoneTexts() -> JSONObject {
        let t = texts
        var out = JSONObject()
        let prefix = "ui.phone.page."
        for key in t.keys(prefix: prefix) { out[String(key.dropFirst(prefix.count))] = .string(t.tr(key)) }
        for style in schema.brushStyles { out["style_\(style)"] = .string(t.tr("ui.brush.\(style)")) }
        for kind in Paper.Kind.allCases { out["paper_\(kind.rawValue)"] = .string(t.tr("ui.paper.\(kind.rawValue)")) }
        let more: [(String, String)] = [
            ("detail_title", "ui.detail.title"), ("detail_hint", "ui.detail.hint"), ("tool_more", "ui.detail.tool_more"),
            ("tool_normal", "ui.detail.tool_normal"), ("tool_less", "ui.detail.tool_less"), ("face", "ui.detail.face"),
            ("rate_up", "ui.rate.up"), ("rate_down", "ui.rate.down"),
        ]
        for (name, key) in more { out[name] = .string(t.tr(key)) }
        out["estimate_none"] = ""
        let export: [(String, String)] = [
            ("x_stroke", "ui.stroke_color"), ("x_width", "ui.stroke_width_scale"), ("x_style", "ui.brush.label"),
            ("x_background", "ui.background"), ("x_paper", "ui.paper.label"), ("x_vignette", "ui.paper.vignette"),
            ("x_frame", "ui.frame.label"), ("x_margin", "ui.frame.margin"), ("x_size", "ui.size_longest"),
            ("x_width_cm", "ui.export_pdf_width"), ("x_mode", "ui.export_mode.label"),
            ("x_mode_process", "ui.export_mode.process"), ("x_mode_strokes", "ui.export_mode.strokes"),
            ("x_length", "ui.export_length"), ("x_hold", "ui.export_hold"), ("preset_applied", "ui.user_presets.applied"),
            ("matrix_fidelity", "ui.matrix.fidelity"), ("matrix_simplicity", "ui.matrix.simplicity"),
        ]
        for (name, key) in export { out[name] = .string(t.tr(key)) }
        for method in RemoteAccess.methods { out["method_\(method)"] = .string(schema.method(method)?.name ?? method) }
        out["lang"] = .string(t.language)
        return out
    }

    /// What /api/status tells (PhoneLink._update): the job running, whether it is paused, how many wait, the last.
    func phoneStatus() -> JSONObject {
        let jobs = queueSnapshot?.jobs ?? []
        let job = jobs.first { $0.isActive }
        let finished: [QueuedJob.Status] = [.done, .failed, .cancelled, .interrupted]
        let ended = jobs.last { finished.contains($0.status) }
        var state: JSONObject = ["busy": .bool(job != nil), "paused": .bool(job?.status == .paused),
                                 "queue": .int(jobs.filter { $0.status == .queued }.count), "job": nil,
                                 "last": ended.map { JSONValue.object(["name": .string($0.target.lastPathComponent),
                                                                       "status": .string($0.status.rawValue)]) } ?? .null]
        if let job {
            let method = job.settings["method"]?.stringValue ?? "clipasso"
            var progress = job.progress * 10000
            progress.round(.toNearestOrEven)
            state["job"] = ["name": .string(job.target.lastPathComponent),
                            "method": .string(schema.method(method)?.name ?? method),
                            "progress": .double(progress / 10000),
                            "eta": .string(PhoneRemote.eta(job.eta))]
        }
        return state
    }

    /// The live sketch of the running job (its newest seed's), else the last finished one's.
    func phonePreview() -> String {
        let jobs = queueSnapshot?.jobs ?? []
        if let job = jobs.first(where: { $0.isActive }), let svg = job.liveSVG.sorted(by: { $0.key < $1.key }).last?.value {
            return svg
        }
        let done = jobs.last { $0.status == .done && $0.bestSVG != nil }
        return done?.bestSVG.flatMap { try? String(contentsOfFile: $0, encoding: .utf8) } ?? ""
    }

    /// Pause, resume, cancel from the phone.
    func phoneCommand(_ name: String) async {
        switch name {
        case "pause", "resume":
            let paused = studio.live.status == .paused
            if (name == "pause") != paused { await pauseOrResume() }
        case "cancel":
            await cancelJob()
        default:
            break
        }
    }

    /// A photo from the phone (PhoneLink._upload): sketched with the studio's settings – or the method's own when
    /// it is another method – into the queue, started at once.
    func phoneUpload(_ file: URL, method: String) async {
        guard let queue else { return }
        let settings = studio.method == method ? studio.jobSettings : schema.method(method)?.defaults ?? [:]
        await queue.add(target: file, settings: settings)
        apply(await queue.snapshot())
        phone.changed()
    }

    /// PhoneApi.handle: what the page asks (the studio's parts follow step by step).
    func phoneAnswer(_ action: String, _ data: JSONObject, payload: Data?) async -> RemoteAnswer {
        switch action {
        case "set_image":
            guard let path = data["path"]?.stringValue else { return .json(["ok": false, "error": "no picture"]) }
            studio.image = URL(filePath: path)
            phone.changed()
            return .json(["ok": true])
        default:
            return .json(["ok": false, "error": "unknown action"])
        }
    }

    /// Start or stop the phone page as the settings say (PhoneLink.apply_settings); its error text, "" when fine.
    @discardableResult
    func applyPhoneSettings() async -> String {
        let want = settings["remote_on"]?.truthy ?? false
        let port = settings["remote_port"]?.intValue ?? RemoteAccess.defaultPort
        phone.keys.tailscale = settings["remote_tailscale"]?.truthy ?? true
        if let server = phone.server, !want || phone.port != port {
            await server.stop()
            phone.stopped()
        }
        guard want, phone.server == nil, let web = resources.web else { return phone.error }
        _ = phone.keys.token()  // (made here)
        _ = phone.keys.pin()
        let page = RemotePage(phoneDir: web.appending(path: "phone"), iconsDir: web.appending(path: "icons"),
                              version: version)
        let router = RemoteRouter(app: AppRemoteBridge(model: self), page: page, secrets: phone.keys.secrets,
                                  uploadDir: settings.outputDir.appending(path: RemoteAccess.uploadDir),
                                  iconFile: web.appending(path: "app_icon.png"), fontsDir: web.appending(path: "fonts"))
        do {
            let server = try RemoteServer(router: router, port: port)
            let actual = try await server.start()
            phone.started(server, port: actual)
        } catch {
            phone.stopped(error: texts.tr("ui.phone.port_busy", ["port": "\(port)", "error": "\(error)"]))
        }
        return phone.error
    }

    /// The phone page on or off (the settings' switch).
    func setPhoneOn(_ on: Bool) async {
        _ = updateSettings { $0["remote_on"] = .bool(on) }
        await applyPhoneSettings()
    }

    func setPhonePort(_ port: Int) async {
        guard (1024 ... 65535).contains(port), port != (settings["remote_port"]?.intValue ?? RemoteAccess.defaultPort)
        else { return }
        _ = updateSettings { $0["remote_port"] = .int(port) }
        await applyPhoneSettings()
    }

    func setPhoneTailscale(_ on: Bool) {
        _ = updateSettings { $0["remote_tailscale"] = .bool(on) }
        phone.keys.tailscale = on
    }
}
