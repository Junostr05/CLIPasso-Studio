import CoreImage
import CoreImage.CIFilterBuiltins
import StudioApp
import StudioCore
import SwiftUI

/// Settings → Phone (phone_ui.PhoneCard, the remote part): the switch; while the page runs its QR code (it signs the
/// phone in), the fixed address and the PIN for when the phone no longer knows the code, the network (home or
/// tailnet), the port and a new access code; why it does not run (a port in use).
struct PhoneSettings: View {
    @Environment(AppModel.self) private var model
    @State private var pin = ""
    @State private var port = ""
    @State private var viaTailscale = false
    @State private var tailscaleIP = ""
    @State private var localIP = ""

    var body: some View {
        let t = model.texts
        let phone = model.phone
        Section {
            Toggle(t.tr("ui.phone.remote"), isOn: Binding(get: { model.settings["remote_on"]?.truthy ?? false },
                                                        set: { on in Task { await model.setPhoneOn(on) } }))
            if phone.running {
                running(t, phone)
            }
            if !phone.error.isEmpty {
                Label { Text(verbatim: phone.error) } icon: { Image(systemName: "exclamationmark.triangle") }
                    .foregroundStyle(Color(hex: Palette.light.warning))
            }
        } header: {
            Text(t.tr("ui.phone.title"))
        } footer: {
            Text(t.tr("ui.phone.desc")).foregroundStyle(.secondary)
        }
        .task(id: phone.running) { refresh() }
    }

    @ViewBuilder
    private func running(_ t: Texts, _ phone: PhoneRemote) -> some View {
        let tailscaleOn = model.settings["remote_tailscale"]?.truthy ?? true
        let address = viaTailscale && tailscaleOn && !tailscaleIP.isEmpty ? tailscaleIP : localIP
        let link = phone.url(address: address)
        let fixed = phone.fixedURL(address: address)
        let _ = phone.revision  // (a new code or PIN: shown again)
        HStack(alignment: .top, spacing: Spacing.spaceL) {
            Group {
                if let qr = Self.qrCode(link) {
                    Image(nsImage: qr).interpolation(.none).resizable()
                } else {
                    Color.clear
                }
            }
            .frame(width: 150, height: 150)
            .accessibilityLabel(Text(t.tr("ui.phone.qr_link")))
            VStack(alignment: .leading, spacing: Spacing.spaceS) {
                Text(.init(t.tr("ui.phone.fixed", ["url": "[\(fixed)](\(fixed))"])))
                    .textSelection(.enabled)
                HStack {
                    Text(t.tr("ui.phone.pin"))
                    Spacer()
                    TextField(t.tr("ui.phone.pin"), text: $pin)
                        .labelsHidden()
                        .frame(width: 90)
                        .multilineTextAlignment(.center)
                        .help(t.tr("ui.phone.pin_tip"))
                        .onSubmit {
                            if !phone.setPin(pin) { pin = phone.keys.pin() }  // (not six digits: the PIN stays)
                        }
                    Button(t.tr("ui.phone.new_pin"), systemImage: "arrow.clockwise") { pin = phone.newPin() }
                }
                Text(t.tr("ui.phone.pin_hint")).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(verbatim: "\(t.tr("ui.phone.qr_link")) \(link)")
                    .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                if !tailscaleIP.isEmpty || tailscaleOn {
                    Toggle(t.tr("ui.phone.tailscale"), isOn: Binding(get: { tailscaleOn },
                                                                     set: { model.setPhoneTailscale($0) }))
                        .help(t.tr("ui.phone.tailscale_tip"))
                    if tailscaleOn, !tailscaleIP.isEmpty {
                        Picker(t.tr("ui.phone.tailscale"), selection: $viaTailscale) {
                            Text(t.tr("ui.phone.net_lan")).tag(false)
                            Text(verbatim: "Tailscale").tag(true)
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                        .fixedSize()
                    }
                    if tailscaleOn {
                        Text(t.tr(tailscaleIP.isEmpty ? "ui.phone.tailscale_missing" : "ui.phone.tailscale_hint"))
                            .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                }
                HStack {
                    Text(t.tr("ui.phone.port"))
                    Spacer()
                    TextField(t.tr("ui.phone.port"), text: $port)
                        .labelsHidden()
                        .frame(width: 80)
                        .onSubmit {
                            if let value = Int(port) { Task { await model.setPhonePort(value) } }
                        }
                }
                Button(t.tr("ui.phone.new_code"), systemImage: "arrow.clockwise") { phone.newToken() }
                    .help(t.tr("ui.phone.new_code_tip"))
                Text(t.tr("ui.phone.remote_hint")).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func refresh() {
        pin = model.phone.keys.pin()
        port = "\(model.phone.port)"
        localIP = PhoneRemote.localAddress()
        tailscaleIP = PhoneRemote.tailscaleAddress()
        viaTailscale = (model.settings["remote_tailscale"]?.truthy ?? true) && !tailscaleIP.isEmpty  // (4.2.4: first)
    }

    /// remote.qr_png: the QR code of `text` (error correction M), crisp.
    static func qrCode(_ text: String) -> NSImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 6, y: 6)),
              let cg = CIContext().createCGImage(output, from: output.extent)
        else { return nil }
        return NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height))
    }
}
