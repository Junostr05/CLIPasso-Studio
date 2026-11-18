import Foundation
import Observation
import StudioCore

/// The detail brush (detail_edit.DetailEditDialog with its DetailCanvas): the map of where the sketch should have more
/// detail and where less, painted over the photo with a soft brush; 30 steps back and forth, all normal again, and
/// portrait mode – the faces' eyes, nose and mouth marked "more" over what is painted. "Use map" has the engine keep
/// it with the image (an all-normal map removes it).
@Observable
public final class DetailEditorModel: Identifiable {
    /// the image the map is of
    public let image: URL
    public private(set) var map: DetailMap
    /// counts the changes (the view draws its overlay anew for each)
    public private(set) var version = 0
    public var tool = DetailEditing.Tool.more
    /// the brush's diameter in pixels of the map
    public var brush: Int
    /// the slider's range
    public let brushes: ClosedRange<Int>
    /// portrait mode is looking for faces
    public private(set) var finding = false
    /// the last search found no face (until the next change)
    public private(set) var noFace = false
    @ObservationIgnored private var undoStack: [[UInt8]] = []
    @ObservationIgnored private var redoStack: [[UInt8]] = []
    public private(set) var canUndo = false
    public private(set) var canRedo = false

    public init(image: URL, map: DetailMap) {
        self.image = image
        self.map = map
        brush = DetailEditing.startBrush(width: map.width, height: map.height)
        brushes = DetailEditing.brushRange(start: brush)
    }

    public var width: Int { map.width }
    public var height: Int { map.height }

    /// The shares of the image with more and with less detail (0 … 1).
    public var share: (more: Double, less: Double) { DetailEditing.share(map) }

    /// The brush pressed at map position (x, y): one dab – a step back undoes the whole stroke.
    public func beginStroke(x: Double, y: Double) {
        snapshot()
        DetailEditing.dab(&map, x: x, y: y, brush: brush, tool: tool)
        changed()
    }

    /// The brush moved on from `a` to `b` while pressed.
    public func continueStroke(from a: (x: Double, y: Double), to b: (x: Double, y: Double)) {
        DetailEditing.line(&map, from: a, to: b, brush: brush, tool: tool)
        changed()
    }

    public func undo() {
        guard let last = undoStack.popLast() else { return }
        redoStack.append(map.values)
        map.values = last
        changed()
    }

    public func redo() {
        guard let next = redoStack.popLast() else { return }
        undoStack.append(map.values)
        map.values = next
        changed()
    }

    /// Alles normal (a step back returns).
    public func clear() {
        set(DetailMap(width: map.width, height: map.height))
    }

    /// Portrait mode's faces over the painted map (nil: no face found).
    public func faces(_ found: DetailMap?) {
        guard let found else {
            noFace = true
            return
        }
        set(DetailEditing.merged(map, found))
    }

    func setFinding(_ on: Bool) {
        finding = on
    }

    /// One brush larger or smaller, as the mask editor's keys: a quarter more or a fifth less, and one pixel.
    public func step(_ direction: Int) {
        let next = Int(Double(brush) * (direction > 0 ? 1.25 : 0.8)) + direction
        brush = min(brushes.upperBound, max(brushes.lowerBound, next))
    }

    private func set(_ next: DetailMap) {
        snapshot()
        map = next
        changed()
    }

    private func snapshot() {
        undoStack.append(map.values)
        if undoStack.count > DetailEditing.undoSteps {
            undoStack.removeFirst(undoStack.count - DetailEditing.undoSteps)
        }
        redoStack.removeAll()
    }

    private func changed() {
        noFace = false
        version += 1
        (canUndo, canRedo) = (!undoStack.isEmpty, !redoStack.isEmpty)
    }
}

#if canImport(ImageIO)
    import CoreGraphics
    import ImageIO
    import UniformTypeIdentifiers

    public extension AppModel {
        /// What portrait mode found.
        enum Faces: Equatable, Sendable {
            case found(DetailMap)
            case none
            /// the face detector is not downloaded (the download is asked for)
            case missingModel
            case failed(String)
        }

        /// The detail brush of the studio's image: the map the engine keeps for it, at the size the studio paints
        /// it (nil without an image).
        func detailEditor() async throws -> DetailEditorModel? {
            guard let image = studio.image, FileManager.default.fileExists(atPath: image.path) else { return nil }
            guard let engine else { throw EngineFailure(code: "engine_gone", message: "the engine is not running") }
            let answer = try await engine.request("detail", ["image": .string(image.path)])
            let o = answer.objectValue ?? [:]
            let (width, height) = (o["width"]?.intValue ?? 0, o["height"]?.intValue ?? 0)
            guard width > 0, height > 0 else { throw MaskFile.ReadError(description: "the engine gave no map size") }
            var map = DetailMap(width: width, height: height)
            if let path = o["map"]?.stringValue {
                let file = URL(filePath: path)
                defer { try? FileManager.default.removeItem(at: file) }  // (the engine's temporary picture)
                map = try await Self.readMap(file, width: width, height: height)
            }
            return DetailEditorModel(image: image, map: map)
        }

        /// Gesicht finden: the engine looks for faces in its own process; their map is laid over the painted one.
        /// Without the detector its download is asked for (the editor's button then tries again).
        @discardableResult
        func findFaces(_ editor: DetailEditorModel) async -> Faces {
            guard let engine, let queue, !editor.finding else { return .failed("the engine is not running") }
            editor.setFinding(true)
            defer { editor.setFinding(false) }
            await queue.begin()  // (its notices bring "portrait_ready")
            let key = editor.image.path
            facesArrived[key] = nil
            do {
                _ = try await engine.request("portrait", ["image": .string(key)])
            } catch let failure as EngineFailure where failure.code == "missing_model" {
                downloadModels([failure.message])
                return .missingModel
            } catch {
                return .failed(String(describing: error))
            }
            let event: EngineEvent
            if let arrived = facesArrived.removeValue(forKey: key) {
                event = arrived
            } else {
                event = await withCheckedContinuation { faceWaiters[key] = $0 }
            }
            guard event.kind == "portrait_ready" else {
                return .failed(event.data["message"]?.stringValue ?? "")
            }
            guard let path = event.data["map"]?.stringValue else {
                editor.faces(nil)
                return .none
            }
            let file = URL(filePath: path)
            defer { try? FileManager.default.removeItem(at: file) }
            do {
                let found = try await Self.readMap(file, width: editor.width, height: editor.height)
                editor.faces(found)
                return .found(found)
            } catch {
                return .failed(String(describing: error))
            }
        }

        /// Karte verwenden: the engine keeps the map with the image (an all-normal map removes it).
        func applyDetails(_ editor: DetailEditorModel) async throws {
            guard let engine else { throw EngineFailure(code: "engine_gone", message: "the engine is not running") }
            let file = FileManager.default.temporaryDirectory.appending(path: "detail-\(UUID().uuidString).png")
            defer { try? FileManager.default.removeItem(at: file) }
            let map = editor.map
            try await Task.detached(executorPreference: OwnThreads.shared) {
                try AppModel.writeGrey(map.values, width: map.width, height: map.height, to: file)
            }.value
            _ = try await engine.request("save_detail", ["image": .string(editor.image.path), "map": .string(file.path)])
        }

        /// Whether the engine keeps a detail map for the studio's image (the button's tooltip says so).
        func hasDetails() async -> Bool {
            guard let image = studio.image, let engine,
                  let answer = try? await engine.request("detail", ["image": .string(image.path)])
            else { return false }
            if let path = answer.objectValue?["map"]?.stringValue { try? FileManager.default.removeItem(atPath: path) }
            return answer.objectValue?["has"]?.truthy ?? false
        }

        /// A portrait notice: to the search waiting for it, or kept until it waits.
        internal func faceNotice(_ event: EngineEvent) {
            guard let image = event.data["image"]?.stringValue else { return }
            if let waiter = faceWaiters.removeValue(forKey: image) {
                waiter.resume(returning: event)
            } else {
                facesArrived[image] = event
            }
        }

        /// An 8-bit grey PNG of the engine as a map of the size expected.
        nonisolated static func readMap(_ url: URL, width: Int, height: Int) async throws -> DetailMap {
            try await Task.detached(executorPreference: OwnThreads.shared) {
                let read = try MaskFile.read(url)
                guard read.width == width, read.height == height else {
                    throw MaskFile.ReadError(description: "the map is \(read.width)×\(read.height), not \(width)×\(height)")
                }
                return DetailMap(width: width, height: height,
                                 values: read.values.map { UInt8(($0 * 255).rounded()) })
            }.value
        }

        /// Bytes as an 8-bit grey PNG (the engine reads a painted mask or map so).
        nonisolated static func writeGrey(_ bytes: [UInt8], width: Int, height: Int, to url: URL) throws {
            guard let provider = CGDataProvider(data: Data(bytes) as CFData),
                  let image = CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 8,
                                      bytesPerRow: width, space: CGColorSpaceCreateDeviceGray(),
                                      bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
                                      provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent),
                  let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)
            else { throw MaskFile.ReadError(description: "the picture could not be written") }
            CGImageDestinationAddImage(destination, image, nil)
            guard CGImageDestinationFinalize(destination) else {
                throw MaskFile.ReadError(description: "the picture could not be written")
            }
        }
    }
#endif
