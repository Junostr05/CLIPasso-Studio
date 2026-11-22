// The app's icon as macOS draws it – the Liquid Glass of AppIcon.icon is drawn by the system (IconServices), not
// by the artwork – in the light and the dark appearance, 1024 px, each on a plain ground; for the CI's screenshots.
//
//   swift macos/scripts/icon_snapshot.swift "CLIPasso Studio.app" OUT_DIR
import AppKit

let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    FileHandle.standardError.write(Data("usage: icon_snapshot.swift APP OUT_DIR\n".utf8))
    exit(2)
}
let app = arguments[1]
let out = URL(fileURLWithPath: arguments[2])
_ = NSApplication.shared
let icon = NSWorkspace.shared.icon(forFile: app)
let size = 1024
for (name, appearance, ground) in [("light", NSAppearance.Name.aqua, 0.94), ("dark", NSAppearance.Name.darkAqua, 0.12)] {
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
                                     samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                     bytesPerRow: 0, bitsPerPixel: 0),
          let look = NSAppearance(named: appearance)
    else { exit(1) }
    look.performAsCurrentDrawingAppearance {
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSColor(white: ground, alpha: 1).setFill()
        NSRect(x: 0, y: 0, width: size, height: size).fill()
        icon.draw(in: NSRect(x: 0, y: 0, width: size, height: size))
        NSGraphicsContext.restoreGraphicsState()
    }
    let file = out.appendingPathComponent("app-icon-\(name).png")
    try rep.representation(using: .png, properties: [:])?.write(to: file)
    print(file.path)
}
