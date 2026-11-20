import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// A photo from the camera (WebcamDialog): the countdown, the file's name, the picture mirrored when wished and
/// used in the studio. (The camera itself is tested on a real Mac.)
@Suite struct WebcamTests {
    @Test func theCountdown() async {
        let webcam = WebcamModel()
        let seen = Counter()
        webcam.sleep = { seen.add(seen.last + 1) }
        #expect(await webcam.countdown() && webcam.left == 0)
        #expect(seen.last == 3)  // (3, 2, 1 – then the picture)
        webcam.sleep = { throw CancellationError() }
        #expect(await !webcam.countdown() && webcam.left == 0)
    }

    @Test func theFilesName() {
        let folder = URL(filePath: "/Ergebnisse/_webcam")
        var date = DateComponents()
        (date.year, date.month, date.day, date.hour, date.minute, date.second) = (2026, 11, 20, 9, 5, 7)
        let when = Calendar.current.date(from: date)!
        #expect(WebcamModel.photoURL(in: folder, at: when, exists: { _ in false }).lastPathComponent
            == "webcam-20261120-090507.png")
        let taken: Set<String> = ["webcam-20261120-090507.png", "webcam-20261120-090507-2.png"]
        #expect(WebcamModel.photoURL(in: folder, at: when, exists: { taken.contains($0.lastPathComponent) })
            .lastPathComponent == "webcam-20261120-090507-3.png")
    }

    @Test func aPhotoInTheStudio() throws {
        let out = FileManager.default.temporaryDirectory.appending(path: "webcam-\(UUID().uuidString)")
        let model = try AppModel(resources: AppModelTests.resources(engine: nil),
                                 store: AppModelTests.store(language: "de", ["output_dir": .string(out.path)]))
        // two pixels: red left, blue right
        let picture = PixelImage(width: 2, height: 1, bytes: [255, 0, 0, 255, 0, 0, 255, 255])
        #expect(model.webcamMirror)
        let mirrored = try model.useWebcamPhoto(picture)
        #expect(mirrored.deletingLastPathComponent().lastPathComponent == "_webcam" && model.studio.image == mirrored)
        #expect(PixelImage.read(mirrored)?.bytes == [0, 0, 255, 255, 255, 0, 0, 255])
        model.setWebcamMirror(false)
        #expect(model.settings["webcam_mirror"] == false)
        let plain = try model.useWebcamPhoto(picture)
        #expect(plain != mirrored && PixelImage.read(plain)?.bytes == picture.bytes)
    }
}
