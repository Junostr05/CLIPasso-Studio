import Foundation
#if canImport(AppKit)
    import AppKit
#endif
#if canImport(UserNotifications)
    import UserNotifications
#endif

/// What the app tells the Mac while jobs run (gui/controller._keep_awake, main_window's taskbar progress and its
/// notification): no sleep while computing, the progress on the Dock icon, a notification when a job ends while
/// the window is in the background.
public protocol AppSignals: AnyObject {
    /// the system does not sleep while it is on (the display may)
    func keepAwake(_ on: Bool)
    /// the running job's progress on the Dock icon, 0 … 1 (nil: none)
    func dockProgress(_ fraction: Double?)
    /// whether the app is in front (then a finished job needs no notification)
    var isActive: Bool { get }
    /// a notification, and the Dock icon asks for attention once (QApplication.alert)
    func notify(title: String, body: String)
}

/// The Mac's: a process activity against idle sleep, a progress bar drawn into the Dock tile, a user notification
/// (asked for once). Without a running application (the tests) it does nothing.
public final class MacSignals: AppSignals {
    private var activity: (any NSObjectProtocol)?
    private var shownProgress: Double??

    public init() {}

    public func keepAwake(_ on: Bool) {
        if on, activity == nil {
            activity = ProcessInfo.processInfo.beginActivity(options: [.idleSystemSleepDisabled, .userInitiated],
                                                             reason: "CLIPasso Studio computes a sketch")
        } else if !on, let activity {
            ProcessInfo.processInfo.endActivity(activity)
            self.activity = nil
        }
    }

    public func dockProgress(_ fraction: Double?) {
        #if canImport(AppKit)
            // (drawn again only when a whole percent changes)
            let rounded = fraction.map { ($0 * 100).rounded() / 100 }
            guard let app = NSApp, shownProgress != .some(rounded) else { return }
            shownProgress = .some(rounded)
            let tile = app.dockTile
            if let rounded {
                let view = (tile.contentView as? DockProgressView) ?? DockProgressView()
                view.fraction = rounded
                tile.contentView = view
            } else {
                tile.contentView = nil
            }
            tile.display()
        #endif
    }

    public var isActive: Bool {
        #if canImport(AppKit)
            NSApp?.isActive ?? true
        #else
            true
        #endif
    }

    public func notify(title: String, body: String) {
        #if canImport(AppKit) && canImport(UserNotifications)
            guard let app = NSApp, Bundle.main.bundleURL.pathExtension == "app" else { return }
            app.requestUserAttention(.informationalRequest)
            let center = UNUserNotificationCenter.current()
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
            Task {  // (asked once; macOS remembers the answer)
                guard (try? await center.requestAuthorization(options: [.alert, .sound])) == true else { return }
                try? await center.add(request)
            }
        #endif
    }
}

#if canImport(AppKit)
    /// The app's icon with a progress bar along its bottom (as Windows shows it on the taskbar button).
    final class DockProgressView: NSView {
        var fraction = 0.0

        override func draw(_ dirtyRect: NSRect) {
            NSApp.applicationIconImage?.draw(in: bounds)
            let bar = NSRect(x: bounds.width * 0.1, y: bounds.height * 0.06, width: bounds.width * 0.8,
                             height: bounds.height * 0.1)
            let radius = bar.height / 2
            NSColor.black.withAlphaComponent(0.55).setFill()
            NSBezierPath(roundedRect: bar, xRadius: radius, yRadius: radius).fill()
            var done = bar.insetBy(dx: 2, dy: 2)
            done.size.width *= max(0, min(1, fraction))
            NSColor.controlAccentColor.setFill()
            NSBezierPath(roundedRect: done, xRadius: done.height / 2, yRadius: done.height / 2).fill()
        }
    }
#endif
