import StudioApp
import StudioCore
import SwiftUI

/// The queue is done: the Mac sleeps or shuts down after the countdown (dialogs.CountdownDialog) – *now* or Cancel.
struct CountdownSheet: View {
    @Environment(AppModel.self) private var model
    let countdown: WhenDoneCountdown

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(model.texts.tr("ui.queue.done_title"))
                .font(.title2.weight(.semibold))
                .accessibilityAddTraits(.isHeader)
            Text(countdown.text(model.texts))
                .monospacedDigit()
            ProgressView(value: Double(countdown.seconds - countdown.left), total: Double(max(countdown.seconds, 1)))
            HStack {
                Spacer()
                Button(model.texts.tr("ui.cancel"), role: .cancel) { countdown.cancel() }
                    .keyboardShortcut(.cancelAction)
                Button(model.texts.tr("ui.queue.done_now_\(countdown.action.rawValue)")) { countdown.now() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(Spacing.spaceXl)
        .frame(width: 420)
    }
}
