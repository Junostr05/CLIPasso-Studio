import Foundation

/// QColor(name) as the studio's web page and Lottie read a colour (Qt 6): "#rgb", "#rrggbb", "#aarrggbb",
/// "#rrrgggbbb", "#rrrrggggbbbb" – or one of Qt's 148 colour names (in any case, white space around it ignored) or
/// "transparent". Anything else – rgb(), an unknown name – is no colour to it.
enum QtColour {
    /// QColor.colorNames() with their colours (Fixtures/export/qcolor.json checks the list against Qt's)
    static let names: [String: RGB] = {
        var out: [String: RGB] = [:]
        for entry in table.split(whereSeparator: { $0 == " " || $0 == "\n" }) {
            let parts = entry.split(separator: "=")
            guard parts.count == 2, let v = Int(parts[1], radix: 16) else { continue }
            out[String(parts[0])] = RGB(v >> 16, v >> 8 & 0xFF, v & 0xFF)
        }
        return out
    }()

    private static let table = """
        aliceblue=f0f8ff antiquewhite=faebd7 aqua=00ffff aquamarine=7fffd4 azure=f0ffff beige=f5f5dc
        bisque=ffe4c4 black=000000 blanchedalmond=ffebcd blue=0000ff blueviolet=8a2be2 brown=a52a2a
        burlywood=deb887 cadetblue=5f9ea0 chartreuse=7fff00 chocolate=d2691e coral=ff7f50 cornflowerblue=6495ed
        cornsilk=fff8dc crimson=dc143c cyan=00ffff darkblue=00008b darkcyan=008b8b darkgoldenrod=b8860b
        darkgray=a9a9a9 darkgreen=006400 darkgrey=a9a9a9 darkkhaki=bdb76b darkmagenta=8b008b
        darkolivegreen=556b2f darkorange=ff8c00 darkorchid=9932cc darkred=8b0000 darksalmon=e9967a
        darkseagreen=8fbc8f darkslateblue=483d8b darkslategray=2f4f4f darkslategrey=2f4f4f darkturquoise=00ced1
        darkviolet=9400d3 deeppink=ff1493 deepskyblue=00bfff dimgray=696969 dimgrey=696969 dodgerblue=1e90ff
        firebrick=b22222 floralwhite=fffaf0 forestgreen=228b22 fuchsia=ff00ff gainsboro=dcdcdc ghostwhite=f8f8ff
        gold=ffd700 goldenrod=daa520 gray=808080 green=008000 greenyellow=adff2f grey=808080 honeydew=f0fff0
        hotpink=ff69b4 indianred=cd5c5c indigo=4b0082 ivory=fffff0 khaki=f0e68c lavender=e6e6fa
        lavenderblush=fff0f5 lawngreen=7cfc00 lemonchiffon=fffacd lightblue=add8e6 lightcoral=f08080
        lightcyan=e0ffff lightgoldenrodyellow=fafad2 lightgray=d3d3d3 lightgreen=90ee90 lightgrey=d3d3d3
        lightpink=ffb6c1 lightsalmon=ffa07a lightseagreen=20b2aa lightskyblue=87cefa lightslategray=778899
        lightslategrey=778899 lightsteelblue=b0c4de lightyellow=ffffe0 lime=00ff00 limegreen=32cd32 linen=faf0e6
        magenta=ff00ff maroon=800000 mediumaquamarine=66cdaa mediumblue=0000cd mediumorchid=ba55d3
        mediumpurple=9370db mediumseagreen=3cb371 mediumslateblue=7b68ee mediumspringgreen=00fa9a
        mediumturquoise=48d1cc mediumvioletred=c71585 midnightblue=191970 mintcream=f5fffa mistyrose=ffe4e1
        moccasin=ffe4b5 navajowhite=ffdead navy=000080 oldlace=fdf5e6 olive=808000 olivedrab=6b8e23
        orange=ffa500 orangered=ff4500 orchid=da70d6 palegoldenrod=eee8aa palegreen=98fb98 paleturquoise=afeeee
        palevioletred=db7093 papayawhip=ffefd5 peachpuff=ffdab9 peru=cd853f pink=ffc0cb plum=dda0dd
        powderblue=b0e0e6 purple=800080 red=ff0000 rosybrown=bc8f8f royalblue=4169e1 saddlebrown=8b4513
        salmon=fa8072 sandybrown=f4a460 seagreen=2e8b57 seashell=fff5ee sienna=a0522d silver=c0c0c0
        skyblue=87ceeb slateblue=6a5acd slategray=708090 slategrey=708090 snow=fffafa springgreen=00ff7f
        steelblue=4682b4 tan=d2b48c teal=008080 thistle=d8bfd8 tomato=ff6347 transparent=000000 turquoise=40e0d0
        violet=ee82ee wheat=f5deb3 white=ffffff whitesmoke=f5f5f5 yellow=ffff00 yellowgreen=9acd32
        """

    /// The colour, nil when Qt would not read one ("transparent" reads as black, its alpha 0).
    static func read(_ text: String) -> RGB? {
        if text.hasPrefix("#") {
            let hex = text.dropFirst()
            guard hex.allSatisfy(\.isHexDigit) else { return nil }
            let digits: Int
            switch hex.count {
            case 3: return Int(hex, radix: 16).map { RGB(($0 >> 8) * 17, ($0 >> 4 & 0xF) * 17, ($0 & 0xF) * 17) }
            case 6: digits = 2
            case 8: return read("#" + String(hex.suffix(6)))  // (#aarrggbb: the alpha first)
            case 9: digits = 3
            case 12: digits = 4
            default: return nil
            }
            // (each part as many digits long: its top byte)
            let parts = (0 ..< 3).compactMap { i -> Int? in
                let start = hex.index(hex.startIndex, offsetBy: i * digits)
                return Int(hex[start ..< hex.index(start, offsetBy: digits)], radix: 16).map { $0 >> (4 * (digits - 2)) }
            }
            return parts.count == 3 ? RGB(parts) : nil
        }
        let name = text.trimmingCharacters(in: .whitespaces).lowercased()
        return name == "transparent" ? RGB(0, 0, 0) : names[name]
    }
}
