import AVFoundation
import AppKit
import CoreImage
import StudioApp
import StudioCore
import SwiftUI

/// "Photo from the webcam" (dialogs.WebcamDialog): the camera's live picture (mirrored if wished), the camera to use,
/// a countdown of three seconds, then the picture is the studio's. macOS asks once whether the app may use the camera.
struct WebcamSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var camera = CameraFeed()
    @State private var webcam = WebcamModel()
    @State private var problem = ""
    @State private var shooting = false

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.webcam.title")).font(.title2)
            ZStack {
                Rectangle().fill(.black)
                if let frame = camera.frame {
                    Image(decorative: frame, scale: 1)
                        .resizable().scaledToFit()
                        .scaleEffect(x: model.webcamMirror ? -1 : 1, y: 1)
                        .accessibilityLabel(t.tr("ui.webcam.title"))
                } else if !problem.isEmpty {
                    Text(verbatim: problem).foregroundStyle(.white).multilineTextAlignment(.center).padding()
                }
                if webcam.left > 0 {
                    Text(verbatim: "\(webcam.left)").font(.system(size: 64, weight: .bold)).foregroundStyle(.white)
                        .accessibilityHidden(true)
                }
            }
            .frame(minWidth: 512, minHeight: 384)
            .clipShape(RoundedRectangle(cornerRadius: Radius.card))
            HStack {
                Picker(t.tr("ui.webcam.title"), selection: Binding(get: { camera.selected }, set: { camera.use($0) })) {
                    ForEach(camera.devices, id: \.uniqueID) { Text(verbatim: $0.localizedName).tag(Optional($0.uniqueID)) }
                }
                .labelsHidden()
                .disabled(camera.devices.isEmpty)
                Toggle(t.tr("ui.webcam.mirror"), isOn: Binding(get: { model.webcamMirror }, set: { model.setWebcamMirror($0) }))
            }
            HStack {
                Spacer()
                Button(t.tr("ui.cancel")) { dismiss() }.keyboardShortcut(.cancelAction)
                Button(t.tr("ui.webcam.shoot"), systemImage: "camera") { shoot() }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(camera.frame == nil || shooting)
            }
        }
        .padding(Spacing.spaceXl)
        .task {
            switch await camera.start() {
            case .running: problem = ""
            case .noCamera: problem = t.tr("ui.webcam.no_camera")
            case .denied: problem = t.tr("ui.mac.webcam.denied")
            }
        }
        .onDisappear { camera.stop() }
    }

    /// _start_countdown, then take: the latest picture, kept and used.
    private func shoot() {
        shooting = true
        Task {
            defer { shooting = false }
            guard await webcam.countdown(), let frame = camera.frame, let picture = PixelImage.from(frame) else { return }
            do {
                try model.useWebcamPhoto(picture)
                dismiss()
            } catch {
                problem = String(describing: error)
            }
        }
    }
}

/// The camera's pictures: the devices, the one in use, its latest picture.
@Observable
final class CameraFeed {
    enum Start { case running, noCamera, denied }

    private(set) var devices: [AVCaptureDevice] = []
    private(set) var selected: String?
    private(set) var frame: CGImage?
    @ObservationIgnored private let session = AVCaptureSession()
    @ObservationIgnored private let receiver = FrameReceiver()
    @ObservationIgnored private let queue = DispatchQueue(label: "webcam")

    func start() async -> Start {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: break
        case .notDetermined:
            guard await AVCaptureDevice.requestAccess(for: .video) else { return .denied }
        default: return .denied
        }
        devices = AVCaptureDevice.DiscoverySession(deviceTypes: [.builtInWideAngleCamera, .external, .continuityCamera],
                                                   mediaType: .video, position: .unspecified).devices
        guard let first = devices.first else { return .noCamera }
        let output = AVCaptureVideoDataOutput()
        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        receiver.onFrame = { [weak self] image in Task { @MainActor in self?.frame = image } }
        output.setSampleBufferDelegate(receiver, queue: queue)
        session.beginConfiguration()
        if session.canAddOutput(output) { session.addOutput(output) }
        session.commitConfiguration()
        use(first.uniqueID)
        return .running
    }

    /// _use_camera: another camera.
    func use(_ id: String?) {
        guard let id, let device = devices.first(where: { $0.uniqueID == id }),
              let input = try? AVCaptureDeviceInput(device: device)
        else { return }
        selected = id
        let box = CaptureBox(session: session, input: input)
        queue.async {
            let session = box.session
            session.beginConfiguration()
            for old in session.inputs { session.removeInput(old) }
            if let input = box.input, session.canAddInput(input) { session.addInput(input) }
            session.commitConfiguration()
            if !session.isRunning { session.startRunning() }
        }
    }

    func stop() {
        let box = CaptureBox(session: session, input: nil)
        queue.async { box.session.stopRunning() }
    }
}

/// The session and an input handed to the camera's queue (AVFoundation's objects are used there only).
private struct CaptureBox: @unchecked Sendable {
    let session: AVCaptureSession
    let input: AVCaptureDeviceInput?
}

/// Turns the camera's buffers into pictures (on the camera's queue).
private nonisolated final class FrameReceiver: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    var onFrame: (@Sendable (CGImage) -> Void)?
    private let context = CIContext()

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                                   from connection: AVCaptureConnection)
    {
        guard let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let image = CIImage(cvPixelBuffer: buffer)
        guard let picture = context.createCGImage(image, from: image.extent) else { return }
        onFrame?(picture)
    }
}
