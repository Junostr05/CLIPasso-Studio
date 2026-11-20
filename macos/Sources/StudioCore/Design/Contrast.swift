import Foundation

/// A colour as #RRGGBB (or #RGB) → its channels.
public func rgb(_ hex: String) -> RGB? {
    var digits = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
    if digits.count == 3 { digits = digits.map { "\($0)\($0)" }.joined() }
    guard digits.count == 6, let value = Int(digits, radix: 16) else { return nil }
    return RGB(value >> 16 & 0xFF, value >> 8 & 0xFF, value & 0xFF)
}

/// WCAG 2 relative luminance (as tests/test_theme_contrast.py computes it).
func luminance(_ c: RGB) -> Double {
    func channel(_ v: Int) -> Double {
        let s = Double(v) / 255
        return s <= 0.03928 ? s / 12.92 : pow((s + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b)
}

/// The WCAG contrast ratio of two colours (1 … 21); 1 when one is not a colour.
public func contrastRatio(_ a: String, _ b: String) -> Double {
    guard let x = rgb(a), let y = rgb(b) else { return 1 }
    let (l1, l2) = (luminance(x), luminance(y))
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)
}
