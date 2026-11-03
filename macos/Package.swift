// swift-tools-version: 6.2
// StudioCore: the Mac app's work behind the window – the engine process, the job queue, the job folders, the gallery,
// the parameter schema, the model downloads – without AppKit or SwiftUI, so `swift test` runs on Linux as well.
import PackageDescription

let package = Package(
    name: "StudioCore",
    platforms: [.macOS(.v26)],
    products: [
        .library(name: "StudioCore", targets: ["StudioCore"])
    ],
    targets: [
        .target(name: "StudioCore"),
        .testTarget(
            name: "StudioCoreTests",
            dependencies: ["StudioCore"],
            resources: [.copy("Fixtures"), .copy("Support/fake_engine.py")]
        ),
    ],
    swiftLanguageModes: [.v6]
)
