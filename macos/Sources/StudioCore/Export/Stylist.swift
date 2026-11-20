import Foundation

/// A brush style for the exports (brush.STYLES): the engine draws sketches in it (its op "stylize") – the strokes
/// become filled outlines, grain, halos … in plain SVG, which SketchRenderer draws. The exports call it where the
/// studio calls brush.stylize_svg: on the sketch restyled and framed, for an animation on each frame, for the SVG
/// that draws itself on each stroke. "plain" asks no one.
///
/// The exports run on threads of their own (OwnThreads) and call it synchronously; the app's stylist waits there
/// for the engine's answer.
public struct Stylist: Sendable {
    public let style: String
    /// the style colours black strokes (brush.RECOLOURING: a ballpoint's blue, a glow …)
    public let recolours: Bool
    private let draw: @Sendable ([String]) throws -> [String]

    public init(style: String, recolours: Bool = false, draw: @escaping @Sendable ([String]) throws -> [String]) {
        self.style = style
        self.recolours = recolours
        self.draw = draw
    }

    public struct StyleError: Error, CustomStringConvertible, Sendable {
        public let description: String
    }

    public static let plain = Stylist(style: "plain") { $0 }

    public var isPlain: Bool { style == "plain" }

    /// The sketches in the style, in their order.
    public func callAsFunction(_ svgs: [String]) throws -> [String] {
        guard !isPlain, !svgs.isEmpty else { return svgs }
        let styled = try draw(svgs)
        guard styled.count == svgs.count else {
            throw StyleError(description: "the style \(style) gave \(styled.count) of \(svgs.count) sketches")
        }
        return styled
    }

    public func callAsFunction(_ svg: String) throws -> String { try self([svg])[0] }
}
