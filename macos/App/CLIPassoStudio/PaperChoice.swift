import StudioApp
import StudioCore
import SwiftUI

/// The paper of an export or a print (dialogs.PaperChoice): its kind and its vignette (0 – 100 %). `changed` hears a
/// new kind, so the dialog can give the background the paper's colour (Paper.colours).
struct PaperChoice: View {
    @Environment(AppModel.self) private var model
    @Binding var paper: Paper?
    let changed: (Paper.Kind) -> Void

    var body: some View {
        let t = model.texts
        Picker(t.tr("ui.paper.label"), selection: kind) {
            ForEach(Paper.Kind.allCases, id: \.self) { Text(t.tr("ui.paper.\($0.rawValue)")).tag($0) }
        }
        .help(t.tr("ui.paper.tip"))
        Stepper(value: vignette, in: 0 ... 100, step: 5) {
            LabeledContent(t.tr("ui.paper.vignette"), value: "\(percent) %")
        }
        .help(t.tr("ui.paper.vignette_tip"))
    }

    private var percent: Int { Int(((paper?.vignette ?? 0) * 100).rounded()) }

    private var kind: Binding<Paper.Kind> {
        Binding(get: { paper?.kind ?? Paper.Kind.none }, set: { kind in
            paper = Paper.normalize(kind: kind.rawValue, vignette: .double(Double(percent) / 100))
            changed(kind)
        })
    }

    private var vignette: Binding<Int> {
        Binding(get: { percent }, set: { value in
            paper = Paper.normalize(kind: (paper?.kind ?? Paper.Kind.none).rawValue, vignette: .double(Double(value) / 100))
        })
    }
}
