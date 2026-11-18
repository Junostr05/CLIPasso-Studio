#if canImport(CoreGraphics) && canImport(ImageIO)
    import CoreGraphics
    import Foundation
    import ImageIO
    import Testing
    @testable import StudioCore

    /// Touching up the mask as the studio does (mask_edit.py) – checked against what the studio's own functions made
    /// of the same photos, masks and candidates (Fixtures/mask/edit.json): every click (a part goes, a candidate part
    /// comes in, the magic wand's area, nothing outside the picture) and the brush, pixel for pixel – on a small photo
    /// and on one larger than the copy parts are found on.
    @Suite(.onOwnThreads) struct MaskEditingTests {
        static func mask(_ name: String) throws -> MaskPlane {
            let read = try MaskFile.read(Fixtures.url(name))
            return MaskPlane(width: read.width, height: read.height, values: read.values.map { $0 >= 0.5 })
        }

        /// An RGB PNG's bytes, row after row (the decoded bytes themselves: drawing would manage their colour).
        static func rgb(_ name: String) throws -> [UInt8] {
            let source = try #require(CGImageSourceCreateWithURL(Fixtures.url(name) as CFURL, nil))
            let image = try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
            let step = image.bitsPerPixel / 8
            try #require(image.bitsPerComponent == 8 && step >= 3, "\(name) is no 8-bit RGB picture")
            let data = try #require(image.dataProvider?.data as Data?)
            var out = [UInt8](repeating: 0, count: image.width * image.height * 3)
            for y in 0 ..< image.height {
                for x in 0 ..< image.width {
                    for c in 0 ..< 3 { out[(y * image.width + x) * 3 + c] = data[y * image.bytesPerRow + x * step + c] }
                }
            }
            return out
        }

        static func cases() throws -> JSONObject { try #require(Fixtures.json("mask/edit.json").objectValue) }

        @Test func theStudiosNumbers() throws {
            let constants = try #require(try Self.cases()["constants"]?.objectValue)
            #expect(Double(MaskEditing.candidate) == constants["candidate"]?.doubleValue.map { Double(Float($0)) })
            #expect(MaskEditing.pickSide == constants["pick_side"]?.intValue)
            #expect(MaskEditing.wandTolerance == constants["wand_tolerance"]?.intValue)
            #expect(MaskEditing.undoSteps == constants["undo_steps"]?.intValue)
        }

        @Test(arguments: ["photo_small", "photo_large"])
        func clicksAndTheBrushLikeTheStudio(_ name: String) throws {
            let c = try #require((try Self.cases()["photos"]?.arrayValue ?? []).compactMap(\.objectValue)
                .first { $0["name"]?.stringValue == name })
            let mask = try Self.mask("mask/edit_\(name)_mask.png")
            let candidate = try Self.mask("mask/edit_\(name)_candidate.png")
            let photo = try #require(MaskPhoto(width: mask.width, height: mask.height,
                                               rgb: try Self.rgb("mask/edit_\(name).png")))
            for (i, step) in (c["steps"]?.arrayValue ?? []).compactMap(\.objectValue).enumerated() {
                let click = (step["click"]?.arrayValue ?? []).compactMap(\.doubleValue)
                let made = MaskEditing.partClick(mask, candidate: candidate, photo: photo, x: click[0], y: click[1])
                guard let expected = step["out"]?.stringValue else {
                    #expect(made == nil, "\(name) click \(i)")
                    continue
                }
                let want = try Self.mask(expected)
                let differing = made.map { zip($0.values, want.values).filter { $0 != $1 }.count } ?? -1
                #expect(differing == 0, "\(name) click \(i): \(differing) pixels differ")
            }
            var brushed = mask
            for stroke in (c["strokes"]?.arrayValue ?? []).compactMap(\.arrayValue) {
                let a = (stroke[1].arrayValue ?? []).compactMap(\.doubleValue)
                let (r, value) = (stroke[3].doubleValue ?? 1, stroke[4].truthy)
                if stroke[0].stringValue == "dab" {
                    MaskEditing.dab(&brushed, x: a[0], y: a[1], r: r, value: value)
                } else {
                    let b = (stroke[2].arrayValue ?? []).compactMap(\.doubleValue)
                    MaskEditing.line(&brushed, from: (a[0], a[1]), to: (b[0], b[1]), r: r, value: value)
                }
            }
            let want = try Self.mask("mask/edit_\(name)_brushed.png")
            #expect(zip(brushed.values, want.values).filter { $0 != $1 }.isEmpty, "\(name): the brush")
        }
    }
#endif
