import Foundation

/// The images of a folder or a drop, as the studio collects them (gui/drop.py): image files by their extension, a
/// folder's own sorted by name, then – when asked for – its subfolders' in name order; hidden folders, the app's
/// working folders (_edited, _pasted, …) and folders of its own results (with a job.json or job_state.json) are
/// skipped.
public enum ImageFiles {
    /// drop.IMAGE_EXT
    public static let extensions = [".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif", ".heic", ".heif",
                                    ".avif"]
    static let skippedFolders = [".", "_edited", "_pasted", "_webcam", "_continued"]
    static let jobFiles = ["job.json", "job_state.json"]  // (jobs.STATE_FILE)

    public static func isImage(_ name: String) -> Bool {
        let lower = name.lowercased()
        return extensions.contains { lower.hasSuffix($0) }
    }

    /// drop.image_files: the images of `folder`, with those of its subfolders when `recursive`.
    public static func inFolder(_ folder: URL, recursive: Bool = false) -> [URL] {
        let manager = FileManager.default
        guard !jobFiles.contains(where: { manager.fileExists(atPath: folder.appending(path: $0).path) }),
              let names = try? manager.contentsOfDirectory(atPath: folder.path)
        else { return [] }
        var files: [String] = []
        var folders: [String] = []
        for name in names {
            var isFolder: ObjCBool = false
            if manager.fileExists(atPath: folder.appending(path: name).path, isDirectory: &isFolder), isFolder.boolValue {
                folders.append(name)
            } else {
                files.append(name)  // (also a broken link, as os.walk counts it)
            }
        }
        var out = files.filter(isImage).sorted { before($0.lowercased(), $1.lowercased()) }
            .map { folder.appending(path: $0) }
        guard recursive else { return out }
        for name in folders.filter({ name in !skippedFolders.contains { name.hasPrefix($0) } }).sorted(by: before) {
            let sub = folder.appending(path: name, directoryHint: .isDirectory)
            if (try? sub.resourceValues(forKeys: [.isSymbolicLinkKey]))?.isSymbolicLink == true { continue }
            out += inFolder(sub, recursive: true)  // (os.walk does not follow a link to a folder)
        }
        return out
    }

    /// Whether the folder has a folder in it (QueuePage._add_folder asks then whether to take its images too).
    public static func hasSubfolders(_ folder: URL) -> Bool {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []
        return names.contains { name in
            var isFolder: ObjCBool = false
            return FileManager.default.fileExists(atPath: folder.appending(path: name).path, isDirectory: &isFolder)
                && isFolder.boolValue
        }
    }

    /// drop.dropped_images: dropped image files as they are, dropped folders with every image in them and their
    /// subfolders – each image once, in the order dropped.
    public static func dropped(_ urls: [URL]) -> [URL] {
        var out: [URL] = []
        for url in urls where url.isFileURL {
            var isFolder: ObjCBool = false
            guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isFolder) else { continue }
            if isFolder.boolValue {
                out += inFolder(url, recursive: true)
            } else if isImage(url.lastPathComponent) {
                out.append(url)
            }
        }
        var seen = Set<String>()
        return out.filter { seen.insert($0.standardizedFileURL.path).inserted }
    }

    /// Python's order of strings: by code points.
    private static func before(_ a: String, _ b: String) -> Bool {
        a.unicodeScalars.lexicographicallyPrecedes(b.unicodeScalars)
    }
}
