import Foundation
import StudioCore

/// The studio canvas's views besides the sketch (studio.py's modes): the photo as the method used it, the attention
/// map, the object mask, the condition or background – of the job under way from its events, of a finished one from
/// its folder.
public extension AppModel {
    /// The method whose views the canvas shows: the finished job's, else the studio's.
    var viewMethod: String {
        if !studio.live.isActive, let result = studio.result { return result.method }
        return studio.method
    }

    /// A view's picture (PNG or the file's bytes); nil when the job has none.
    func studioView(_ kind: String) -> Data? {
        let live = studio.live
        if live.isActive || studio.result == nil {
            return kind == "attention" ? live.attention : live.views[kind]
        }
        guard let result = studio.result, let summary = JobFolder.summary(at: result.jobDir) else { return nil }
        let run = result.runs.first { $0.name == result.selected }?.runDir
        return JobViews.files(jobDir: result.jobDir, summary: summary, run: run)[kind]
            .flatMap { try? Data(contentsOf: $0) }
    }

    /// The views there are now, in their order (_views).
    var studioViews: [String] {
        JobViews.kinds(for: viewMethod).filter { studioView($0) != nil }
    }
}
