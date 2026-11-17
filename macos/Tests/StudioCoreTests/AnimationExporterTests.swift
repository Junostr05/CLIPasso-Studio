#if canImport(CoreGraphics) && canImport(ImageIO)
    import CoreGraphics
    import Foundation
    import ImageIO
    import Testing
    @testable import StudioCore
    #if canImport(AVFoundation)
        import AVFoundation
    #endif

    /// The studio's animations made here: the drawing process of a run and the sketch stroke by stroke, as a GIF
    /// (ImageIO), an MP4 (AVFoundation) and PNG frames for the engine's WebP – the plan's frames and delays, ink in
    /// eight steps on a plain background, the paper under the strokes, a transparent background only for WebP.
    @Suite struct AnimationExporterTests {
        static func sketch(_ name: String) throws -> String { String(decoding: try Fixtures.data(name), as: UTF8.self) }

        static func job(_ mode: Animation.Mode, _ format: Animation.Format, size: Int = 64, runDir: URL? = nil,
                        svg: String? = nil, length: Double? = 1, hold: Double = 0.5) throws -> AnimationJob
        {
            var options = ExportOptions()
            options.size = size
            options.background = "#FFFFFF"
            return AnimationJob(mode: mode, format: format, options: options, length: length, hold: hold,
                                svg: try svg ?? sketch("animation/drawing.svg"), runDir: runDir)
        }

        /// A run with three saved steps (and its best one, the second).
        static func run() throws -> URL {
            let run = FileManager.default.temporaryDirectory.appending(path: "anim-\(UUID().uuidString)")
            let logs = run.appending(path: "svg_logs")
            try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
            for (i, name) in ["svg/lines.svg", "svg/cubic.svg", "svg/closed_bg.svg"].enumerated() {
                try Fixtures.data(name).write(to: logs.appending(path: "svg_iter\(i * 10).svg"))
            }
            try Data(#"{"best_iter": 10, "method": "clipasso"}"#.utf8).write(to: run.appending(path: "config.json"))
            return run
        }

        static func colours(_ image: CGImage) -> Set<UInt32> {
            var rgba = [UInt8](repeating: 0, count: image.width * image.height * 4)
            rgba.withUnsafeMutableBytes { raw in
                let context = CGContext(data: raw.baseAddress, width: image.width, height: image.height, bitsPerComponent: 8,
                                        bytesPerRow: image.width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
            }
            return Set(stride(from: 0, to: rgba.count, by: 4).map {
                UInt32(rgba[$0]) << 24 | UInt32(rgba[$0 + 1]) << 16 | UInt32(rgba[$0 + 2]) << 8 | UInt32(rgba[$0 + 3])
            })
        }

        @Test func aGIFStrokeByStroke() throws {
            let job = try Self.job(.strokes, .gif)
            let url = FileManager.default.temporaryDirectory.appending(path: "strokes-\(UUID().uuidString).gif")
            defer { try? FileManager.default.removeItem(at: url) }
            var progress: [Int] = []
            let count = try AnimationExporter.gif(job, to: url) { done, _ in progress.append(done) }
            let plan = Animation.plan(50, length: 1, fps: 50, hold: 0.5, format: .gif, size: 64)  // (1 s: 50 drawn steps)
            #expect(count == plan.frames.count && progress.last == count)
            let source = try #require(CGImageSourceCreateWithURL(url as CFURL, nil))
            #expect(CGImageSourceGetCount(source) == count)
            let delays = (0 ..< count).map { i -> Double in
                let properties = CGImageSourceCopyPropertiesAtIndex(source, i, nil) as? [CFString: Any]
                let gif = properties?[kCGImagePropertyGIFDictionary] as? [CFString: Any]
                return (gif?[kCGImagePropertyGIFUnclampedDelayTime] as? Double) ?? (gif?[kCGImagePropertyGIFDelayTime] as? Double) ?? -1
            }
            #expect(zip(delays, plan.durations).allSatisfy { abs($0 * 1000 - $1) < 1 }, "\(delays)")
            let first = try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
            let last = try #require(CGImageSourceCreateImageAtIndex(source, count - 1, nil))
            #expect(first.width == 64 && first.height == 64)
            #expect(Self.colours(last).count > 2 && Self.colours(last).count <= Animation.inkLevels)  // (ink in steps)
            #expect(Self.colours(first).count < Self.colours(last).count || Self.colours(first).count <= 2)
        }

        @Test func theDrawingProcessOfARun() throws {
            let run = try Self.run()
            defer { try? FileManager.default.removeItem(at: run) }
            var frames: [AnimationExporter.Frame] = []
            let count = try AnimationExporter.frames(try Self.job(.process, .webp, runDir: run, length: nil)) { frames.append($0) }
            let plan = Animation.plan(2, length: nil, fps: 20, hold: 0.5, format: .webp)  // (up to the best step: two)
            #expect(count == plan.frames.count && frames.map(\.milliseconds) == plan.durations)
            #expect(throws: AnimationError(code: "export_no_logs")) {
                try AnimationExporter.frames(try Self.job(.process, .gif)) { _ in }
            }
            let erased = #"<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224"></svg>"#
            #expect(throws: AnimationError(code: "export_no_strokes")) {
                try AnimationExporter.frames(try Self.job(.strokes, .gif, svg: erased)) { _ in }
            }
        }

        /// WebP's frames: PNG files with their durations; a transparent background stays transparent there.
        @Test func pngFramesForTheEnginesWebP() throws {
            var job = try Self.job(.strokes, .webp, length: 0.5, hold: 0)
            job.options.background = nil
            let folder = FileManager.default.temporaryDirectory.appending(path: "webp-\(UUID().uuidString)")
            defer { try? FileManager.default.removeItem(at: folder) }
            let durations = try AnimationExporter.pngFrames(job, to: folder)
            let files = try FileManager.default.contentsOfDirectory(atPath: folder.path).sorted()
            #expect(files.count == durations.count && files.first == "frame_00000.png")
            let source = try #require(CGImageSourceCreateWithURL(folder.appending(path: files[0]) as CFURL, nil))
            let image = try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
            #expect(Self.colours(image).contains(0))  // (transparent pixels)
            job.format = .gif  // (GIF and MP4: white instead)
            var gifFrame: CGImage?
            try AnimationExporter.frames(job) { if gifFrame == nil { gifFrame = $0.image } }
            #expect(!Self.colours(try #require(gifFrame)).contains(0))
        }

        /// On paper the frames are in full colour, the paper under the strokes.
        @Test func onPaper() throws {
            var job = try Self.job(.strokes, .gif)
            job.options.paper = Paper(kind: .kraft)
            var first: CGImage?
            try AnimationExporter.frames(job) { if first == nil { first = $0.image } }
            #expect(Self.colours(try #require(first)).count > Animation.inkLevels)  // (the paper's texture)
        }

        #if canImport(AVFoundation)
            @Test func anMP4() async throws {
                let job = try Self.job(.strokes, .mp4, size: 100, length: 1, hold: 0.5)
                let url = FileManager.default.temporaryDirectory.appending(path: "strokes-\(UUID().uuidString).mp4")
                defer { try? FileManager.default.removeItem(at: url) }
                let count = try await AnimationExporter.mp4(job, to: url)
                #expect(count == 45)  // (1 s and 0.5 s at 30 fps)
                let asset = AVURLAsset(url: url)
                let duration = try await asset.load(.duration)
                #expect(abs(duration.seconds - 1.5) < 0.05)
                let track = try #require(try await asset.loadTracks(withMediaType: .video).first)
                let size = try await track.load(.naturalSize)
                #expect(size.width == 112 && size.height == 112)  // (100 → a multiple of 16)
            }
        #endif
    }
#endif
