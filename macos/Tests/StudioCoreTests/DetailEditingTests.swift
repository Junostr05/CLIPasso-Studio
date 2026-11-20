#if canImport(CoreGraphics) && canImport(ImageIO)
    import CoreGraphics
    import Foundation
    import ImageIO
    import Testing
    @testable import StudioCore

    /// The detail brush as the studio paints (detail_edit.py) – checked against what the studio's own canvas made
    /// (Fixtures/detail/edit.json): each tool's soft dabs and lines, one after the other over a map that is not all
    /// normal, byte for byte; the overlay the canvas lays over the photo, the dialog's share line, the brush it starts
    /// with and its numbers.
    @Suite struct DetailEditingTests {
        /// The bytes of an 8-bit grey PNG, row after row.
        static func bytes(_ name: String, channels: Int = 1) throws -> (width: Int, height: Int, values: [UInt8]) {
            let source = try #require(CGImageSourceCreateWithURL(Fixtures.url(name) as CFURL, nil))
            let image = try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
            let step = image.bitsPerPixel / 8
            try #require(image.bitsPerComponent == 8 && step >= channels, "\(name): \(image.bitsPerPixel) bits")
            let data = try #require(image.dataProvider?.data as Data?)
            var out = [UInt8](repeating: 0, count: image.width * image.height * channels)
            for y in 0 ..< image.height {
                for x in 0 ..< image.width {
                    for c in 0 ..< channels {
                        out[(y * image.width + x) * channels + c] = data[y * image.bytesPerRow + x * step + c]
                    }
                }
            }
            return (image.width, image.height, out)
        }

        static func map(_ name: String) throws -> DetailMap {
            let read = try bytes(name)
            return DetailMap(width: read.width, height: read.height, values: read.values)
        }

        static func cases() throws -> JSONObject { try #require(Fixtures.json("detail/edit.json").objectValue) }

        /// The studio's overlay as RGBA, from its opacity and its kind of colour (1 more, 2 less).
        static func overlay(_ name: String) throws -> [UInt8] {
            let alpha = try bytes("detail/edit_overlay_\(name)_alpha.png").values
            let kind = try bytes("detail/edit_overlay_\(name)_kind.png").values
            var rgba = [UInt8](repeating: 0, count: alpha.count * 4)
            for i in alpha.indices where kind[i] != 0 {
                let c = kind[i] == 1 ? DetailEditing.moreRGB : DetailEditing.lessRGB
                (rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2], rgba[i * 4 + 3]) = (c.r, c.g, c.b, alpha[i])
            }
            return rgba
        }

        @Test func theStudiosNumbers() throws {
            let c = try Self.cases()
            let constants = try #require(c["constants"]?.objectValue)
            #expect(DetailEditing.editSide == constants["edit_side"]?.intValue)
            #expect(DetailEditing.undoSteps == constants["undo_steps"]?.intValue)
            #expect(Int(DetailEditing.normal) == constants["normal"]?.intValue)
            for tool in DetailEditing.Tool.allCases {
                #expect(Int(tool.value) == constants["tools"]?.objectValue?[tool.rawValue]?.intValue)
            }
            let more = DetailEditing.moreRGB, less = DetailEditing.lessRGB
            #expect([more.r, more.g, more.b].map(Int.init) == constants["more_rgb"]?.arrayValue?.compactMap(\.intValue))
            #expect([less.r, less.g, less.b].map(Int.init) == constants["less_rgb"]?.arrayValue?.compactMap(\.intValue))
            for photo in (c["photos"]?.arrayValue ?? []).compactMap(\.objectValue) {
                let size = (photo["size"]?.arrayValue ?? []).compactMap(\.intValue)
                let brush = DetailEditing.startBrush(width: size[0], height: size[1])
                #expect(brush == photo["brush"]?.intValue, "\(size)")
                let range = DetailEditing.brushRange(start: brush)
                #expect([range.lowerBound, range.upperBound] == photo["slider"]?.arrayValue?.compactMap(\.intValue))
            }
        }

        @Test func dabsLinesAndTheOverlayLikeTheStudio() throws {
            let c = try Self.cases()
            var map = try Self.map("detail/edit_start.png")
            let shares = (c["shares"]?.arrayValue ?? []).map { ($0.arrayValue ?? []).compactMap(\.stringValue) }
            func shown(_ map: DetailMap) -> [String] {
                let s = DetailEditing.share(map)
                return [String(format: "%.0f", s.more * 100), String(format: "%.0f", s.less * 100)]
            }
            #expect(DetailEditing.overlay(map) == (try Self.overlay("start")), "the overlay of the start")
            #expect(shown(map) == shares.first)
            for (i, stroke) in (c["strokes"]?.arrayValue ?? []).compactMap(\.objectValue).enumerated() {
                let tool = try #require(DetailEditing.Tool(rawValue: stroke["tool"]?.stringValue ?? ""))
                let brush = try #require(stroke["brush"]?.intValue)
                let a = (stroke["from"]?.arrayValue ?? []).compactMap(\.doubleValue)
                if stroke["kind"]?.stringValue == "dab" {
                    DetailEditing.dab(&map, x: a[0], y: a[1], brush: brush, tool: tool)
                } else {
                    let b = (stroke["to"]?.arrayValue ?? []).compactMap(\.doubleValue)
                    DetailEditing.line(&map, from: (a[0], a[1]), to: (b[0], b[1]), brush: brush, tool: tool)
                }
                let want = try Self.map(try #require(stroke["out"]?.stringValue))
                let differing = Swift.zip(map.values, want.values).filter { $0 != $1 }.count
                #expect(differing == 0, "stroke \(i) (\(tool), \(brush)): \(differing) pixels differ")
                #expect(shown(map) == shares[i + 1], "stroke \(i)")
                map = want  // (each stroke on the studio's map, so that one difference is not counted again)
            }
            #expect(DetailEditing.overlay(map) == (try Self.overlay("end")), "the overlay of the end")
        }

        @Test func theFacesOverThePaintedMap() {
            let painted = DetailMap(width: 3, height: 1, values: [0, 200, 128])
            let faces = DetailMap(width: 3, height: 1, values: [150, 140, 128])
            #expect(DetailEditing.merged(painted, faces).values == [150, 200, 128])
            #expect(DetailEditing.merged(painted, DetailMap(width: 1, height: 1)) == painted)
        }
    }
#endif
