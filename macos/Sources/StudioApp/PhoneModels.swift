import Foundation
import StudioCore

/// Models downloaded on the phone's request (PhoneApi._download): the window's download, one model after the other;
/// how it ended is kept once the window's download is over.
struct PhoneDownload {
    let keys: [String]
    /// "done", "cancelled" or "failed" once it is over (nil: still running)
    var ended: String?
    var error = ""
}

public extension AppModel {
    /// The models the studio's settings choose, by task, and the ones they need (the engine's model_roles; nil when it
    /// cannot say).
    internal func phoneModelRoles() async -> JSONObject? {
        guard let engine else { return nil }
        let others = JSONObject(RemoteAccess.methods.filter { schema.method($0) != nil }.map {
            ($0, .object(studio.settings(for: $0)))
        })
        let answer = try? await engine.request("model_roles", ["method": .string(studio.method),
                                                               "settings": .object(studio.jobSettings),
                                                               "methods": .object(others)], timeout: .seconds(10))
        return answer?.objectValue
    }

    /// _download_state: the phone's download – which model of how many, how far, how it ended.
    internal func phoneDownloadState() -> JSONValue {
        guard var d = phone.download else { return .null }
        var (name, index, done, total) = ("", d.keys.count, Int64(0), Int64(0))
        if d.ended == nil {
            switch models.stage {
            case .asking(let keys) where keys == d.keys:
                (name, index) = (models.name(d.keys.first ?? ""), 1)
            case .downloading(let key, let a, let b) where d.keys.contains(key):
                (name, index, done, total) = (models.name(key), (d.keys.firstIndex(of: key) ?? 0) + 1, a, b)
            case .converting(let key) where d.keys.contains(key):
                let size = catalog.spec(key)?.downloadSize ?? 0
                (name, index, done, total) = (models.name(key), (d.keys.firstIndex(of: key) ?? 0) + 1, size, size)
            case .failed(let why):
                (d.ended, d.error) = ("failed", why)
            default:
                d.ended = d.keys.allSatisfy { modelState($0) != .missing } ? "done" : "cancelled"
            }
            phone.download = d
        }
        return ["status": .string(d.ended ?? "running"), "name": .string(name), "index": .int(index),
                "count": .int(d.keys.count), "done": .int(Int(done)), "total": .int(Int(total)),
                "error": .string(d.error)]
    }

    /// The app's switches the phone may change, in the order of APP_SETTINGS.
    internal static let phoneSwitches = ["check_updates", "keep_awake", "notify"]

    /// The answers about the models and the app's settings (3.8); nil: not one of them.
    internal func phoneModelsAnswer(_ action: String, _ data: JSONObject) async -> RemoteAnswer? {
        func no(_ why: String) -> RemoteAnswer { .json(["ok": false, "error": .string(why)]) }
        let failed = texts.tr("ui.phone.page.failed")
        switch action {
        case "get_models":
            let roles = await phoneModelRoles()
            let used = Set(roles?["in_use"]?.arrayValue?.compactMap(\.stringValue) ?? [])
            let groups: [JSONValue] = catalog.groups.compactMap { group in
                let specs = catalog.models.filter { $0.group == group.id }
                guard !specs.isEmpty else { return nil }
                return ["key": .string(group.id), "name": .string(texts.tr(group.title)),
                        "models": .array(specs.map { spec in
                            let state = modelState(spec.key)
                            return ["key": .string(spec.key), "name": .string(spec.name),
                                    "purpose": .string(purpose(spec)), "mb": .int(spec.storedSizeMB),
                                    "available": .bool(state != .missing), "used": .bool(used.contains(spec.key)),
                                    "bundled": .bool(state == .included), "experimental": .bool(spec.experimental)]
                        })]
            }
            let method = studio.methodSchema
            let rows: [JSONValue] = (roles?["roles"]?.arrayValue ?? []).compactMap { item in
                guard let r = item.objectValue, let key = r["key"]?.stringValue, let param = method?.param(key)
                else { return nil }
                let choices: [JSONValue] = (r["choices"]?.arrayValue ?? []).compactMap { c in
                    guard let c = c.objectValue, let value = c["value"] else { return nil }
                    return ["value": value, "label": .string(PhoneStudio.choiceLabel(param, value, texts: texts)),
                            "experimental": .bool(c["experimental"]?.truthy ?? false)]
                }
                let names = (r["models"]?.arrayValue ?? []).compactMap(\.stringValue).map(models.name)
                return ["category": .string(texts.tr("ui.models.role.\(r["category"]?.stringValue ?? "")")),
                        "key": .string(key), "label": .string(PhoneStudio.label(param, texts: texts)),
                        "value": r["value"] ?? .null, "enabled": .bool(r["enabled"]?.truthy ?? false),
                        "choices": .array(choices), "models": .array(names.map(JSONValue.string)),
                        "missing": r["missing"] ?? [], "experimental": .bool(r["experimental"]?.truthy ?? false)]
            }
            return .json(["ok": true, "groups": .array(groups), "method": .string(method?.name ?? studio.method),
                          "roles": .array(rows), "download": phoneDownloadState()])
        case "do_download_models":
            switch models.stage {
            case .idle, .failed: break
            default: return no(texts.tr("ui.phone.page.download_running"))
            }
            var keys = data["keys"]?.arrayValue?.compactMap(\.stringValue) ?? []
            if data["keys"]?.truthy != true {
                keys = (await phoneModelRoles())?["missing"]?.arrayValue?.compactMap(\.stringValue) ?? []
            }
            keys = keys.filter { catalog.spec($0) != nil && modelState($0) == .missing }
            guard !keys.isEmpty else { return no(texts.tr("ui.phone.page.download_nothing")) }
            phone.download = PhoneDownload(keys: keys)
            downloadModels(keys)
            confirmDownload()
            return .json(["ok": true, "count": .int(keys.count)])
        case "do_cancel_download":
            _ = phoneDownloadState()  // (how it ended, if it did)
            if phone.download?.ended == nil, phone.download != nil { cancelDownload() }
            return .json(["ok": true])
        case "do_remove_model":
            let key = PhoneStudio.pyStr(data["key"] ?? "")
            guard catalog.spec(key) != nil, modelState(key) == .installed else { return no(failed) }
            if queueSnapshot?.jobs.contains(where: { $0.isActive }) ?? false {
                return no(texts.tr("ui.phone.page.model_busy"))
            }
            switch models.stage {
            case .idle, .failed: break
            default: return no(texts.tr("ui.phone.page.download_running"))
            }
            do {
                try removeModel(key)
            } catch {
                return no(failed)
            }
            return .json(["ok": true])
        case "get_app_settings":
            // (APP_SETTINGS as far as the Mac app has them: no experimental sketch, betas or warm worker)
            let language: JSONValue = [
                "key": "language", "label": .string(texts.tr("ui.settings.language")), "kind": "choice",
                "value": .string(settings.language),
                "choices": .array(languageChoices.map { ["value": .string($0.id), "label": .string($0.label)] }),
            ]
            return .json(["ok": true, "settings": .array([language] + Self.phoneSwitches.map {
                ["key": .string($0), "label": .string(texts.tr("ui.settings.\($0)")), "kind": "bool",
                 "value": .bool(isOn($0))]
            })])
        case "do_app_setting":
            switch data["key"]?.stringValue {
            case "language":
                guard let value = data["value"]?.stringValue, languageChoices.contains(where: { $0.id == value }),
                      (try? setLanguage(value)) != nil
                else { return no(failed) }
            case let key? where Self.phoneSwitches.contains(key):
                setOn(key, data["value"]?.truthy ?? false)
            default:
                return no(failed)
            }
            return .json(["ok": true])
        case "get_update":
            // (mode "none": the phone offers no installing – on the Mac it is done by hand, the page says how)
            return .json(["ok": true, "version": .string(version), "phase": .string(updateState.rawValue),
                          "error": .string(updateState == .failed ? texts.tr("ui.update.check_failed") : ""),
                          "latest": .string(Self.plainVersion(latest?.version ?? "")),
                          "notes": .string(latest?.notes ?? ""), "can_install": false, "mode": "none",
                          "done": 0, "total": 0, "last": .null])
        case "do_check_update":
            guard updateState != .checking else { return no(texts.tr("ui.remote_update.busy")) }
            Task { await checkUpdateNow() }  // (the phone asks again in a moment)
            return .json(["ok": true])
        case "do_install_update":
            return no(texts.tr("ui.mac.phone.update_not_here"))
        case "do_cancel_update":
            return .json(["ok": false])
        default:
            return nil
        }
    }
}
