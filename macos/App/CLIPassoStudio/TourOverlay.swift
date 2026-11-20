import StudioApp
import StudioCore
import SwiftUI

/// Where the guide's steps point: the parts of the window by their step's key.
nonisolated struct TourAnchors: PreferenceKey {
    static var defaultValue: [String: Anchor<CGRect>] { [:] }

    static func reduce(value: inout [String: Anchor<CGRect>], nextValue: () -> [String: Anchor<CGRect>]) {
        value.merge(nextValue()) { $1 }
    }
}

extension View {
    /// This part of the window is what the guide's step `key` explains.
    func tourTarget(_ key: String) -> some View {
        anchorPreference(key: TourAnchors.self, value: .bounds) { [key: $0] }
    }
}

/// The guide over the window (tour.Tour): everything dimmed but the part the step explains (with the accent's
/// edge), the card beside it – right of it, else left, below or above, else in the middle; the window below waits
/// until the guide is closed. Esc skips it, ←/→ and Return go through it.
struct TourOverlay: View {
    @Environment(AppModel.self) private var model
    let anchors: [String: Anchor<CGRect>]

    static let pad: CGFloat = 8  // tour.PAD
    static let gap: CGFloat = 16  // tour.GAP
    static let cardWidth: CGFloat = 360
    static let cardHeight: CGFloat = 250  // (about: its place is worked out before it is laid out)

    var body: some View {
        let tour = model.tour
        GeometryReader { geo in
            let full = CGRect(origin: .zero, size: geo.size)
            let target = tour.step.flatMap { anchors[$0.key] }.map { geo[$0].insetBy(dx: -Self.pad, dy: -Self.pad) }
            ZStack(alignment: .topLeading) {
                Path { path in
                    path.addRect(full)
                    if let target { path.addRoundedRect(in: target, cornerSize: CGSize(width: Radius.card, height: Radius.card)) }
                }
                .fill(Color.black.opacity(0.65), style: FillStyle(eoFill: true))
                .contentShape(Rectangle())
                .onTapGesture {}  // (the window below waits)
                .accessibilityHidden(true)
                if let target {
                    RoundedRectangle(cornerRadius: Radius.card)
                        .stroke(Color.accentColor, lineWidth: 2)
                        .frame(width: target.width, height: target.height)
                        .offset(x: target.minX, y: target.minY)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
                card
                    .frame(width: Self.cardWidth)
                    .offset(Self.place(target, in: full.insetBy(dx: 12, dy: 12)))
            }
        }
        .ignoresSafeArea()
    }

    private var card: some View {
        let t = model.texts, tour = model.tour
        return VStack(alignment: .leading, spacing: Spacing.spaceS) {
            Text(verbatim: tour.position(t)).font(.caption).foregroundStyle(.secondary)
            Text(verbatim: tour.title(t)).font(.title2.bold())
            Text(verbatim: tour.text(t)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(t.tr("ui.tour.skip")) { model.tourFinished() }
                    .buttonStyle(.borderless)
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button(t.tr("ui.tour.back")) { tour.back() }
                    .disabled(tour.index == 0)
                    .keyboardShortcut(.leftArrow, modifiers: [])
                Button(t.tr(tour.isLast ? "ui.tour.done" : "ui.tour.next")) {
                    if tour.next() { model.tourFinished() }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                Button("") { if tour.next() { model.tourFinished() } }  // (→ as Return)
                    .keyboardShortcut(.rightArrow, modifiers: [])
                    .frame(width: 0, height: 0).opacity(0).accessibilityHidden(true)
            }
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: Radius.card).fill(.regularMaterial))
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(.isModal)
    }

    /// tour._place: right of the part, else left of it, below, above (or over it); nothing: in the middle.
    static func place(_ target: CGRect?, in area: CGRect) -> CGSize {
        let (w, h) = (cardWidth, cardHeight)
        var pos: CGPoint
        if let target {
            if target.maxX + gap + w <= area.maxX {
                pos = CGPoint(x: target.maxX + gap, y: target.minY)
            } else if target.minX - gap - w >= area.minX {
                pos = CGPoint(x: target.minX - gap - w, y: target.minY)
            } else if target.maxY + gap + h <= area.maxY {
                pos = CGPoint(x: target.minX, y: target.maxY + gap)
            } else {
                pos = CGPoint(x: target.minX, y: max(area.minY, target.minY - gap - h))
            }
        } else {
            pos = CGPoint(x: area.midX - w / 2, y: area.midY - h / 2)
        }
        pos.x = min(max(pos.x, area.minX), area.maxX - w)
        pos.y = min(max(pos.y, area.minY), area.maxY - h)
        return CGSize(width: pos.x, height: pos.y)
    }
}

/// Help ▸ Show the guide.
struct TourCommands: Commands {
    let model: AppModel?

    var body: some Commands {
        CommandGroup(replacing: .help) {
            Button(model?.texts.tr("ui.tour.show") ?? "Tour") { model?.tour.start() }
                .disabled(model == nil)
        }
    }
}
