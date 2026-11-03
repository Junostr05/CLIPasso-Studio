import Foundation

/// A path saved inside a job folder, for where that folder is now (engine/jobs.py `rebase`): the files keep absolute
/// paths – from a Mac or from Windows (`C:\…`) – and the folder may have moved since. A path that exists, that is
/// empty or that does not run through a folder of the job folder's name stays as it is.
public func rebase(_ path: String, jobDir: URL) -> String {
    if path.isEmpty || FileManager.default.fileExists(atPath: path) {
        return path
    }
    let parts = path.replacingOccurrences(of: "\\", with: "/").split(separator: "/").map(String.init)
    let name = jobDir.standardizedFileURL.lastPathComponent
    guard let i = parts.lastIndex(of: name) else { return path }
    let rest = parts[(i + 1)...]
    return rest.isEmpty ? jobDir.path : jobDir.path + "/" + rest.joined(separator: "/")
}

/// The last part of a path from a Mac or from Windows.
func fileName(_ path: String) -> String {
    String(path.split(whereSeparator: { $0 == "/" || $0 == "\\" }).last ?? "")
}
