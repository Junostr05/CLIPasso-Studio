import Foundation
import StudioCore

/// The studio's "My presets" (param_panel's user presets), for the window and the phone alike.
public extension AppModel {
    /// Every own preset, in the order they were made.
    var userPresets: [UserPresets.Preset] {
        UserPresets.all(settings[UserPresets.key], schema: schema)
    }

    /// The own preset the studio's settings are equal to ("" when none).
    var userPreset: String {
        UserPresets.matching(studio.jobSettings, in: settings[UserPresets.key], schema: schema)
    }

    /// apply_user_preset: its settings in the studio – switched to its method; of the same method the files on this
    /// Mac (a start SVG) stay. False when there is no such preset.
    @discardableResult
    func applyUserPreset(_ name: String, method: String? = nil) -> Bool {
        let method = method.flatMap { $0.isEmpty ? nil : $0 } ?? studio.method  // ("method or self._method")
        guard let preset = UserPresets.find(name, method: method, in: settings[UserPresets.key], schema: schema)
        else { return false }
        var values = preset.settings
        if preset.method == studio.method, let m = studio.methodSchema {
            for p in m.params where p.kind == .path {
                values[p.key] = studio.settings[p.key] ?? p.default
            }
        }
        studio.adopt(values)
        return true
    }

    /// save_user_preset: the studio's settings kept under `name`; the name kept ("" for a name of only spaces).
    @discardableResult
    func saveUserPreset(_ name: String) -> String {
        guard let saved = UserPresets.save(.string(name), studio.jobSettings, in: settings[UserPresets.key],
                                           schema: schema)
        else { return "" }
        updateSettings { $0[UserPresets.key] = saved.stored }
        return saved.saved.name
    }

    @discardableResult
    func deleteUserPreset(_ name: String, method: String) -> Bool {
        guard let kept = UserPresets.delete(name, method: method, in: settings[UserPresets.key], schema: schema) else {
            return false
        }
        updateSettings { $0[UserPresets.key] = kept }
        return true
    }
}
