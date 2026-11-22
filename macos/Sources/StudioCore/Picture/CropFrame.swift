import Foundation

/// A rectangle as Qt's QRectF keeps it (right = x + width, bottom = y + height; empty: 0 × 0).
public struct CropRect: Sendable, Equatable {
    public var x, y, width, height: Double

    public init(_ x: Double, _ y: Double, _ width: Double, _ height: Double) {
        (self.x, self.y, self.width, self.height) = (x, y, width, height)
    }

    public static let null = CropRect(0, 0, 0, 0)
    public var isNull: Bool { width == 0 && height == 0 }
    public var right: Double { x + width }
    public var bottom: Double { y + height }

    /// QRectF.intersected: the common part, or the empty rectangle.
    public func intersected(_ o: CropRect) -> CropRect {
        let (l, t) = (max(x, o.x), max(y, o.y))
        let (r, b) = (min(right, o.right), min(bottom, o.bottom))
        return r <= l || b <= t ? .null : CropRect(l, t, r - l, b - t)
    }

    /// QRectF.toRect: each value rounded (half away from zero).
    public var pixels: (x: Int, y: Int, width: Int, height: Int) {
        (Int(x.rounded()), Int(y.rounded()), Int(width.rounded()), Int(height.rounded()))
    }
}

/// The crop frame of the image editor (gui/image_edit.py CropView and ImageEditDialog): the frame in the picture's
/// pixels, held to an aspect ratio if one is chosen, moved and resized by its handles, turned and mirrored with the
/// picture; `steps` records the turns and mirrorings for the pixels (ImageEditSteps).
public struct CropFrame: Sendable, Equatable {
    /// MIN_SIDE: the smallest side of the frame in the picture's pixels
    public static let minSide = 16.0
    /// ASPECTS
    public static let aspects: [(key: String, value: Double?)] = [("free", nil), ("square", 1), ("landscape", 4.0 / 3),
                                                                   ("portrait", 3.0 / 4)]

    public private(set) var width: Double
    public private(set) var height: Double
    public var crop: CropRect
    public private(set) var aspect: Double?
    /// what was done to the picture, in order: +90 / −90 (turned clockwise / anticlockwise), 0 (mirrored)
    public private(set) var steps: [Int] = []

    public init(width: Int, height: Int, crop: CropRect? = nil, aspect: Double? = nil) {
        (self.width, self.height) = (Double(width), Double(height))
        self.crop = crop ?? CropRect(0, 0, Double(width), Double(height))
        self.aspect = aspect
    }

    var bounds: CropRect { CropRect(0, 0, width, height) }

    /// _fit_aspect: the largest rectangle of the aspect ratio inside the current frame (centred).
    public mutating func fitAspect() {
        guard let aspect else {
            crop = crop.intersected(bounds)
            return
        }
        let c = crop.isNull ? bounds : crop
        var (w, h) = (c.width, c.height)
        if w / max(h, 1e-6) > aspect { w = h * aspect } else { h = w / aspect }
        let (cx, cy) = (c.x + c.width / 2, c.y + c.height / 2)
        crop = CropRect(cx - w / 2, cy - h / 2, w, h).intersected(bounds)
    }

    public mutating func setAspect(_ value: Double?) {
        aspect = value
        fitAspect()
    }

    /// drag_to: the frame moved ("move") or resized by a handle (n, s, e, w, ne, nw, se, sw) – like a drag from
    /// `press` (with the frame at `start`) to `point`, in the picture's pixels.
    public mutating func drag(_ handle: String, to point: (Double, Double), from start: CropRect,
                              press: (Double, Double))
    {
        let b = bounds
        if handle == "move" {
            var r = CropRect(start.x + point.0 - press.0, start.y + point.1 - press.1, start.width, start.height)
            r.x = min(max(r.x, 0), b.width - r.width)
            r.y = min(max(r.y, 0), b.height - r.height)
            crop = r
            return
        }
        let x = min(max(point.0, 0), b.width), y = min(max(point.1, 0), b.height)
        var (left, top, right, bottom) = (start.x, start.y, start.right, start.bottom)
        if handle.contains("w") { left = min(x, right - Self.minSide) }
        if handle.contains("e") { right = max(x, left + Self.minSide) }
        if handle.contains("n") { top = min(y, bottom - Self.minSide) }
        if handle.contains("s") { bottom = max(y, top + Self.minSide) }
        if let aspect {  // corners only: the height follows the width
            var w = right - left
            var h = w / aspect
            if handle.contains("n") { top = bottom - h } else { bottom = top + h }
            if top < 0 || bottom > b.height {  // too tall: limit by the height instead
                h = top < 0 ? bottom - max(top, 0) : min(bottom, b.height) - top
                w = h * aspect
                if handle.contains("n") { top = bottom - h } else { bottom = top + h }
                if handle.contains("w") { left = right - w } else { right = left + w }
            }
        }
        crop = CropRect(left, top, right - left, bottom - top).intersected(b)
    }

    /// rotate: the picture and the frame turned by 90° (clockwise) or −90°; a 4:3 frame turns into 3:4.
    public mutating func rotate(_ degrees: Int) {
        let c = crop
        crop = degrees == 90 ? CropRect(height - c.bottom, c.x, c.height, c.width)
            : CropRect(c.y, width - c.right, c.height, c.width)
        aspect = aspect.map { 1 / $0 }
        (width, height) = (height, width)
        steps.append(degrees == 90 ? 90 : -90)
        keepCrop()
    }

    /// flip: the picture and the frame mirrored left to right.
    public mutating func flip() {
        let c = crop
        crop = CropRect(width - c.right, c.y, c.width, c.height)
        steps.append(0)
        keepCrop()
    }

    /// set_image(keep_crop=True): the frame kept (the whole picture when it was empty), fitted again.
    private mutating func keepCrop() {
        if crop.isNull { crop = bounds }
        fitAspect()
    }
}
