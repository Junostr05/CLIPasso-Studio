import Foundation

/// An animation to export: what it shows (the drawing process of the run or the finished sketch stroke by stroke),
/// the format, the export's choices (stroke colour and width, background or paper, frame, size), the drawing's length
/// (nil: the default) and how long the finished sketch stays.
public struct AnimationJob: Sendable {
    public var mode: Animation.Mode
    public var format: Animation.Format
    public var options: ExportOptions
    public var length: Double?
    public var hold: Double
    /// the finished sketch as it is now (touched up or not)
    public var svg: String
    /// its run (the saved steps, its method)
    public var runDir: URL?
    public var photo: SketchFraming.PhotoFrame?

    public init(mode: Animation.Mode, format: Animation.Format, options: ExportOptions, length: Double? = nil,
                hold: Double = 1, svg: String, runDir: URL?, photo: SketchFraming.PhotoFrame? = nil)
    {
        (self.mode, self.format, self.options, self.length, self.hold) = (mode, format, options, length, hold)
        (self.svg, self.runDir, self.photo) = (svg, runDir, photo)
    }
}

/// Why an animation cannot be made: its text is ui.err.<code> (export_no_logs, export_no_strokes).
public struct AnimationError: Error, Equatable, Sendable {
    public let code: String
}

/// The drawn frames of an animation (export.export_animation / export_drawing): their number, the SVG of each –
/// framed as the finished sketch – and the frame rate and length the plan starts from.
public struct DrawnFrames: Sendable {
    public let count: Int
    public let fps: Double
    public let length: Double?
    let read: @Sendable (Int) -> String

    public func svg(_ i: Int) -> String { read(i) }

    public init(_ job: AnimationJob) throws {
        let framing = SketchFraming.make(job.svg, mode: job.options.frame, frame: job.photo,
                                         margin: Double(job.options.margin) / 100)
        switch job.mode {
        case .process:
            let steps = job.runDir.map { Animation.steps(runDir: $0) } ?? []
            guard !steps.isEmpty else { throw AnimationError(code: "export_no_logs") }
            count = steps.count
            fps = 20
            length = job.length
            read = { i in
                let text = (try? String(contentsOf: steps[i], encoding: .utf8)) ?? "<svg xmlns=\"http://www.w3.org/2000/svg\"/>"
                return framing?.apply(text) ?? text
            }
        case .strokes:
            let keep = job.runDir.map { Animation.method(runDir: $0) == "controlsketch" } ?? false
            let drawing = Drawing(svg: framing?.apply(job.svg) ?? job.svg, keepOrder: keep)
            guard drawing.strokeCount > 0 else { throw AnimationError(code: "export_no_strokes") }
            let length = job.length ?? Animation.defaultDrawingLength(strokes: drawing.strokeCount, line: drawing.line)
            let n = max(2, Int((length * Double(Animation.drawStepsPerSecond)).rounded(.toNearestOrEven)))
            count = n
            fps = Double(n) / length
            self.length = length
            read = { i in drawing.frame(Double(i + 1) / Double(n)) }
        }
    }

    /// _one_colour: every stroke black (each method draws black strokes; CLIPasso varies their opacity).
    static func oneColour(_ svg: String) -> Bool {
        let black: Set<String> = ["#000", "#000000", "black", "rgb(0,0,0)"]
        var colours = Set<String>()
        var rest = svg[...]
        while let found = rest.range(of: "stroke=\"") {
            let value = rest[found.upperBound...].prefix { $0 != "\"" }
            colours.insert(value.replacingOccurrences(of: " ", with: "").lowercased())
            rest = rest[found.upperBound...].dropFirst(value.count)
        }
        return colours.subtracting(["none"]).isSubset(of: black)
    }
}

#if canImport(CoreGraphics) && canImport(ImageIO)
    import CoreGraphics
    import ImageIO
    import UniformTypeIdentifiers

    /// The animations drawn with Core Graphics as the studio draws them (export._encode): every frame of the plan in
    /// the export's choices – one stroke colour on a plain background as eight steps of ink (the anti-aliased
    /// edges), else in full colour or on the paper – centred on a canvas whose sides are multiples of 16 for MP4;
    /// a transparent background only for WebP (white for GIF and MP4). GIF here with ImageIO, MP4 with
    /// AVFoundation; WebP gets the frames as PNG files (the engine writes it with Pillow).
    public enum AnimationExporter {
        /// A frame of the plan and how long it stays (ms).
        public struct Frame {
            public let image: CGImage
            public let milliseconds: Double
        }

        struct Look {
            let ink: Bool
            /// nil: transparent
            let background: RGB?
            let palette: [(r: UInt8, g: UInt8, b: UInt8, a: UInt8)]
            let size: (width: Int, height: Int)
            let canvas: (width: Int, height: Int)
            let base: CGImage?
        }

        static func look(_ job: AnimationJob, _ frames: DrawnFrames) throws -> Look {
            let options = job.options
            let ink = (options.strokeColour != nil || DrawnFrames.oneColour(frames.svg(frames.count - 1))) && options.paper == nil
            var background = options.background.flatMap { SketchSVG.color($0) }
            if background == nil, job.format != .webp { background = RGB(255, 255, 255) }
            let stroke = SketchSVG.color(options.strokeColour ?? "#000000") ?? RGB(0, 0, 0)
            let palette = (0 ..< Animation.inkLevels).map { i -> (UInt8, UInt8, UInt8, UInt8) in
                let f = Double(i) / Double(Animation.inkLevels - 1)
                guard let b = background else {
                    return (UInt8(stroke.r), UInt8(stroke.g), UInt8(stroke.b), UInt8((255 * f).rounded(.toNearestOrEven)))
                }
                func mix(_ s: Int, _ b: Int) -> UInt8 { UInt8((Double(b) + Double(s - b) * f).rounded(.toNearestOrEven)) }
                return (mix(stroke.r, b.r), mix(stroke.g, b.g), mix(stroke.b, b.b), 255)
            }
            let size = dims(frames.svg(frames.count - 1), options.size)
            let canvas: (width: Int, height: Int) = job.format == .mp4  // (the video codec wants multiples of 16)
                ? (size.width + (16 - size.width % 16) % 16, size.height + (16 - size.height % 16) % 16) : size
            let base = try options.paper.map {
                try PaperPicture.image($0, width: canvas.width, height: canvas.height, background: options.background)
            }
            return Look(ink: ink, background: background, palette: palette, size: size, canvas: canvas, base: base)
        }

        /// export._dims: the longer side `size`, in the shape of the viewBox (Python's round).
        static func dims(_ svg: String, _ size: Int) -> (width: Int, height: Int) {
            let box = SketchEditing.viewBox(svg)
            guard box.width > 0, box.height > 0 else { return (size, size) }
            let aspect = box.width / box.height
            func round(_ v: Double) -> Int { max(1, Int(v.rounded(.toNearestOrEven))) }
            return aspect >= 1 ? (size, round(Double(size) / aspect)) : (round(Double(size) * aspect), size)
        }

        static func context(_ width: Int, _ height: Int) throws -> CGContext {
            guard let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                                          space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { throw SketchRenderer.RenderError(description: "no bitmap of \(width)×\(height)") }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.interpolationQuality = .high
            return context
        }

        /// One drawn frame: export._ink mapped onto the palette, or the full colour picture.
        static func render(_ svg: String, _ job: AnimationJob, _ look: Look) throws -> CGImage {
            let (cw, ch) = look.canvas
            let (w, h) = look.size
            let rect = CGRect(x: Double(cw - w) / 2, y: Double(ch - h) / 2, width: Double(w), height: Double(h))
            let context = try context(cw, ch)
            if look.ink {  // black on white, its grey (PIL's "L") in eight steps, then the palette's colours
                let sketch = try SketchSVG.parse(SketchExport.restyleSVG(svg, strokeColor: "#000000",
                                                                         widthScale: job.options.widthScale))
                context.setFillColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 1))
                context.fill(CGRect(x: 0, y: 0, width: cw, height: ch))
                SketchRenderer.draw(sketch, in: context, rect: rect)
                guard let data = context.data else { throw SketchRenderer.RenderError(description: "no frame") }
                let pixels = data.bindMemory(to: UInt8.self, capacity: cw * ch * 4)
                let levels = Animation.inkLevels - 1
                for i in 0 ..< cw * ch {
                    let p = pixels + i * 4
                    let grey = (Int(p[0]) * 19595 + Int(p[1]) * 38470 + Int(p[2]) * 7471 + 0x8000) >> 16
                    let colour = look.palette[((255 - grey) * levels + 127) / 255]
                    let a = Int(colour.a)  // (premultiplied)
                    (p[0], p[1], p[2], p[3]) = (UInt8(Int(colour.r) * a / 255), UInt8(Int(colour.g) * a / 255),
                                                UInt8(Int(colour.b) * a / 255), colour.a)
                }
            } else {
                let sketch = try SketchSVG.parse(SketchExport.restyleSVG(svg, strokeColor: job.options.strokeColour,
                                                                         widthScale: job.options.widthScale))
                if let base = look.base {
                    context.draw(base, in: CGRect(x: 0, y: 0, width: cw, height: ch))
                } else if let background = look.background {
                    context.setFillColor(SketchRenderer.cgColor(background))
                    context.fill(CGRect(x: 0, y: 0, width: cw, height: ch))
                }
                SketchRenderer.draw(sketch, in: context, rect: rect)
            }
            guard let image = context.makeImage() else { throw SketchRenderer.RenderError(description: "no frame") }
            return image
        }

        /// The frames of the plan one after another (a drawn frame shown twice is drawn once); a cancelled task
        /// stops between frames (CancellationError). Returns the number of frames.
        @discardableResult
        public static func frames(_ job: AnimationJob, progress: (Int, Int) -> Void = { _, _ in },
                                  each: (Frame) throws -> Void) throws -> Int
        {
            let drawn = try DrawnFrames(job)
            let plan = Animation.plan(drawn.count, length: drawn.length, fps: drawn.fps, hold: job.hold,
                                      format: job.format, size: job.options.size)
            let look = try look(job, drawn)
            var last: (index: Int, image: CGImage)?
            for (k, (i, ms)) in zip(plan.frames, plan.durations).enumerated() {
                if Task.isCancelled { throw CancellationError() }
                let image = try last.flatMap { $0.index == i ? $0.image : nil } ?? render(drawn.svg(i), job, look)
                last = (i, image)
                try each(Frame(image: image, milliseconds: ms))
                progress(k + 1, plan.frames.count)
            }
            return plan.frames.count
        }

        /// The GIF: every frame with its delay (1/100 s), repeating for ever. Returns the number of frames.
        @discardableResult
        public static func gif(_ job: AnimationJob, to url: URL, progress: (Int, Int) -> Void = { _, _ in }) throws -> Int {
            var collected: [Frame] = []
            let count = try frames(job, progress: progress) { collected.append($0) }
            guard let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.gif.identifier as CFString,
                                                                    collected.count, nil)
            else { throw SketchRenderer.RenderError(description: "no GIF writer") }
            let loop = [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]] as CFDictionary
            CGImageDestinationSetProperties(destination, loop)
            for frame in collected {
                let seconds = frame.milliseconds / 1000
                let delay = [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFDelayTime: seconds,
                                                             kCGImagePropertyGIFUnclampedDelayTime: seconds]] as CFDictionary
                CGImageDestinationAddImage(destination, frame.image, delay)
            }
            guard CGImageDestinationFinalize(destination) else {
                try? FileManager.default.removeItem(at: url)
                throw SketchRenderer.RenderError(description: "the GIF was not written")
            }
            return count
        }

        /// The frames as PNG files in `folder` (frame_00000.png …) for the engine's WebP; returns their durations
        /// (ms). A transparent background stays transparent.
        public static func pngFrames(_ job: AnimationJob, to folder: URL, progress: (Int, Int) -> Void = { _, _ in })
            throws -> [Double]
        {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            var durations: [Double] = []
            try frames(job, progress: progress) { frame in
                let name = String(format: "frame_%05d.png", durations.count)
                try SketchRenderer.pngData(frame.image).write(to: folder.appending(path: name))
                durations.append(frame.milliseconds)
            }
            return durations
        }
    }
#endif

#if canImport(AVFoundation) && canImport(CoreGraphics) && canImport(ImageIO)
    import AVFoundation
    import CoreVideo

    public extension AnimationExporter {
        /// The MP4 (H.264, 30 fps, sides in multiples of 16): a drawn frame repeated where the plan repeats it.
        @discardableResult
        static func mp4(_ job: AnimationJob, to url: URL, progress: (Int, Int) -> Void = { _, _ in }) async throws -> Int {
            try? FileManager.default.removeItem(at: url)
            let drawn = try DrawnFrames(job)
            let look = try look(job, drawn)
            let (w, h) = look.canvas
            let writer = try AVAssetWriter(outputURL: url, fileType: .mp4)
            let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
                AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: w, AVVideoHeightKey: h,
            ])
            input.expectsMediaDataInRealTime = false
            let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
                kCVPixelBufferWidthKey as String: w, kCVPixelBufferHeightKey as String: h,
            ])
            guard writer.canAdd(input) else { throw SketchRenderer.RenderError(description: "no MP4 writer") }
            writer.add(input)
            guard writer.startWriting() else {
                throw SketchRenderer.RenderError(description: writer.error.map { String(describing: $0) } ?? "no MP4 writer")
            }
            writer.startSession(atSourceTime: .zero)
            var index = 0
            do {
                try frames(job, progress: progress) { frame in
                    while !input.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.002) }
                    let buffer = try pixelBuffer(frame.image, adaptor: adaptor, width: w, height: h)
                    let time = CMTime(value: CMTimeValue(index), timescale: CMTimeScale(Animation.mp4FPS))
                    guard adaptor.append(buffer, withPresentationTime: time) else {
                        throw SketchRenderer.RenderError(description: writer.error.map { String(describing: $0) } ?? "MP4 frame")
                    }
                    index += 1
                }
            } catch {
                writer.cancelWriting()
                try? FileManager.default.removeItem(at: url)
                throw error
            }
            input.markAsFinished()
            writer.endSession(atSourceTime: CMTime(value: CMTimeValue(index), timescale: CMTimeScale(Animation.mp4FPS)))
            await withCheckedContinuation { (done: CheckedContinuation<Void, Never>) in
                writer.finishWriting { done.resume() }
            }
            guard writer.status == .completed else {
                try? FileManager.default.removeItem(at: url)
                throw SketchRenderer.RenderError(description: writer.error.map { String(describing: $0) } ?? "the MP4 was not written")
            }
            return index
        }

        internal static func pixelBuffer(_ image: CGImage, adaptor: AVAssetWriterInputPixelBufferAdaptor, width: Int,
                                         height: Int) throws -> CVPixelBuffer
        {
            var buffer: CVPixelBuffer?
            if let pool = adaptor.pixelBufferPool {
                CVPixelBufferPoolCreatePixelBuffer(nil, pool, &buffer)
            } else {
                CVPixelBufferCreate(nil, width, height, kCVPixelFormatType_32ARGB, nil, &buffer)
            }
            guard let buffer else { throw SketchRenderer.RenderError(description: "no video frame") }
            CVPixelBufferLockBaseAddress(buffer, [])
            defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
            guard let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let context = CGContext(data: CVPixelBufferGetBaseAddress(buffer), width: width, height: height,
                                          bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer), space: space,
                                          bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)
            else { throw SketchRenderer.RenderError(description: "no video frame") }
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return buffer
        }
    }
#endif
