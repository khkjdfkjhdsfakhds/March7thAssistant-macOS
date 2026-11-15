import Foundation
import AppKit
import ApplicationServices
import CoreGraphics

struct WindowBounds: Codable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct ScreenInfo: Codable {
    let index: Int
    let x: Double
    let y: Double
    let width: Double
    let height: Double
    let visibleX: Double
    let visibleY: Double
    let visibleWidth: Double
    let visibleHeight: Double
    let scale: Double
    let isMain: Bool
}

struct WindowCandidate: Codable {
    let wid: Int
    let pid: Int32
    let owner: String
    let title: String?
    let layer: Int
    let onscreen: Bool
    let bounds: WindowBounds
    let bundleId: String?
    let isActive: Bool
    let isHidden: Bool
}

struct TccStatus: Codable {
    let accessibility: Bool
    let screenRecordingPreflight: Bool
    let windowTitlesVisible: Bool
    let automationSystemEventsStatus: Int32
    let automationFinderStatus: Int32
}

func jsonOut<T: Encodable>(_ value: T, exitCode: Int32 = 0) -> Never {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    if let data = try? encoder.encode(value), let str = String(data: data, encoding: .utf8) {
        print(str)
    }
    exit(exitCode)
}

struct ErrorPayload: Codable {
    let ok: Bool
    let error: String
    let message: String
}

func fail(_ code: String, _ message: String, exitCode: Int32 = 1) -> Never {
    jsonOut(ErrorPayload(ok: false, error: code, message: message), exitCode: exitCode)
}

func parseArgs() -> (cmd: String, opts: [String: String], flags: Set<String>) {
    let args = Array(CommandLine.arguments.dropFirst())
    guard let cmd = args.first else {
        fail("usage", "Usage: pc_helper <tcc-check|window-info|activate|click|drag|key|scroll> [--key val ...]", exitCode: 64)
    }
    var opts: [String: String] = [:]
    var flags: Set<String> = []
    var i = 1
    while i < args.count {
        let arg = args[i]
        if arg.hasPrefix("--") {
            let key = String(arg.dropFirst(2))
            if i + 1 < args.count && !args[i + 1].hasPrefix("--") {
                opts[key] = args[i + 1]
                i += 2
            } else {
                flags.insert(key)
                i += 1
            }
        } else {
            i += 1
        }
    }
    return (cmd, opts, flags)
}

func collectScreens() -> [ScreenInfo] {
    let mainH = NSScreen.screens.first?.frame.height ?? NSScreen.main?.frame.height ?? 0
    return NSScreen.screens.enumerated().map { idx, s in
        // Convert Cocoa bottom-left frame to CGWindow top-left coordinates using primary screen height.
        let topY = mainH > 0 ? (mainH - (s.frame.origin.y + s.frame.height)) : s.frame.origin.y
        let visTopY = mainH > 0 ? (mainH - (s.visibleFrame.origin.y + s.visibleFrame.height)) : s.visibleFrame.origin.y
        return ScreenInfo(
            index: idx,
            x: Double(s.frame.origin.x),
            y: Double(topY),
            width: Double(s.frame.width),
            height: Double(s.frame.height),
            visibleX: Double(s.visibleFrame.origin.x),
            visibleY: Double(visTopY),
            visibleWidth: Double(s.visibleFrame.width),
            visibleHeight: Double(s.visibleFrame.height),
            scale: Double(s.backingScaleFactor),
            isMain: s == NSScreen.main
        )
    }
}

func checkWindowTitlesVisible() -> Bool {
    guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
        return false
    }
    let myPid = ProcessInfo.processInfo.processIdentifier
    for w in list {
        guard let pid = w[kCGWindowOwnerPID as String] as? Int32, pid != myPid else { continue }
        let owner = (w[kCGWindowOwnerName as String] as? String) ?? ""
        if owner == "Window Server" { continue }
        if let name = w[kCGWindowName as String] as? String, !name.isEmpty {
            return true
        }
    }
    return false
}

func runTccCheck() -> Never {
    let ax = AXIsProcessTrusted()
    let sc = CGPreflightScreenCaptureAccess()
    let titles = checkWindowTitlesVisible()
    let seTarget = NSAppleEventDescriptor(bundleIdentifier: "com.apple.systemevents")
    let seStatus = AEDeterminePermissionToAutomateTarget(seTarget.aeDesc, typeWildCard, typeWildCard, false)
    let finderTarget = NSAppleEventDescriptor(bundleIdentifier: "com.apple.finder")
    let finderStatus = AEDeterminePermissionToAutomateTarget(finderTarget.aeDesc, typeWildCard, typeWildCard, false)
    jsonOut(TccStatus(
        accessibility: ax,
        screenRecordingPreflight: sc,
        windowTitlesVisible: titles,
        automationSystemEventsStatus: seStatus,
        automationFinderStatus: finderStatus
    ))
}

struct WindowInfoResponse: Codable {
    let ok: Bool
    let frontmostBundleId: String?
    let frontmostPid: Int32?
    let screens: [ScreenInfo]
    let mainWindow: WindowCandidate?
    let candidates: [WindowCandidate]
}

func runWindowInfo(opts: [String: String], flags: Set<String>) -> Never {
    let targetBundle = opts["bundle"] ?? "com.miHoYo.hkrpg"
    let targetOwner = opts["owner"] ?? "崩坏:星穹铁道"
    let targetPid = opts["pid"].flatMap { Int32($0) }
    let includeAll = flags.contains("all")

    var appsByPid: [Int32: NSRunningApplication] = [:]
    var matchingPids: Set<Int32> = []
    for app in NSWorkspace.shared.runningApplications {
        appsByPid[app.processIdentifier] = app
        let bid = app.bundleIdentifier ?? ""
        let name = app.localizedName ?? ""
        if let tp = targetPid {
            if app.processIdentifier == tp { matchingPids.insert(tp) }
        } else if (!targetBundle.isEmpty && bid == targetBundle) || (!targetOwner.isEmpty && name == targetOwner) {
            matchingPids.insert(app.processIdentifier)
        }
    }

    let listOpt: CGWindowListOption = includeAll ? [.optionAll] : [.optionOnScreenOnly, .excludeDesktopElements]
    let rawList = (CGWindowListCopyWindowInfo(listOpt, kCGNullWindowID) as? [[String: Any]]) ?? []
    var allFallback: [[String: Any]] = rawList
    if !includeAll {
        allFallback = (CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as? [[String: Any]]) ?? rawList
    }

    func parseCandidates(_ list: [[String: Any]]) -> [WindowCandidate] {
        var out: [WindowCandidate] = []
        for w in list {
            guard let pid = w[kCGWindowOwnerPID as String] as? Int32,
                  let wid = w[kCGWindowNumber as String] as? Int,
                  let bDict = w[kCGWindowBounds as String] as? [String: Any],
                  let x = bDict["X"] as? Double,
                  let y = bDict["Y"] as? Double,
                  let width = bDict["Width"] as? Double,
                  let height = bDict["Height"] as? Double else { continue }
            let owner = (w[kCGWindowOwnerName as String] as? String) ?? ""
            let app = appsByPid[pid]
            let bid = app?.bundleIdentifier
            let match = matchingPids.contains(pid)
                || (!targetBundle.isEmpty && bid == targetBundle)
                || (!targetOwner.isEmpty && owner == targetOwner)
            if !match { continue }
            let layer = (w[kCGWindowLayer as String] as? Int) ?? 0
            let onscreen = ((w[kCGWindowIsOnscreen as String] as? Int) ?? 0) != 0
            let title = w[kCGWindowName as String] as? String
            out.append(WindowCandidate(
                wid: wid,
                pid: pid,
                owner: owner,
                title: title,
                layer: layer,
                onscreen: onscreen,
                bounds: WindowBounds(x: x, y: y, width: width, height: height),
                bundleId: bid,
                isActive: app?.isActive ?? false,
                isHidden: app?.isHidden ?? false
            ))
        }
        return out
    }

    var candidates = parseCandidates(rawList)
    if candidates.isEmpty && !includeAll {
        candidates = parseCandidates(allFallback)
    }

    // Prefer onscreen layer-0 windows >= 200x200 with largest area (excludes 1920x30 menubar / 64x64 helper windows).
    let mainWin = candidates
        .filter { $0.layer == 0 && $0.bounds.width >= 200 && $0.bounds.height >= 200 }
        .sorted { a, b in
            if a.onscreen != b.onscreen { return a.onscreen && !b.onscreen }
            return (a.bounds.width * a.bounds.height) > (b.bounds.width * b.bounds.height)
        }
        .first

    let front = NSWorkspace.shared.frontmostApplication
    jsonOut(WindowInfoResponse(
        ok: true,
        frontmostBundleId: front?.bundleIdentifier,
        frontmostPid: front?.processIdentifier,
        screens: collectScreens(),
        mainWindow: mainWin,
        candidates: candidates
    ))
}

struct ActivateResponse: Codable {
    let ok: Bool
    let targetPid: Int32
    let previousPid: Int32?
    let alreadyActive: Bool
    let isActiveNow: Bool
}

func runActivate(opts: [String: String]) -> Never {
    let previous = NSWorkspace.shared.frontmostApplication?.processIdentifier
    var app: NSRunningApplication? = nil
    if let pidStr = opts["pid"], let pid = Int32(pidStr) {
        app = NSRunningApplication(processIdentifier: pid)
    } else if let bid = opts["bundle"] {
        app = NSRunningApplication.runningApplications(withBundleIdentifier: bid).first
    } else {
        app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.miHoYo.hkrpg").first
    }
    guard let target = app else {
        fail("app_not_running", "Target application is not running")
    }
    if target.isActive {
        jsonOut(ActivateResponse(ok: true, targetPid: target.processIdentifier, previousPid: previous, alreadyActive: true, isActiveNow: true))
    }
    let waitMs = Int(opts["wait-ms"] ?? "250") ?? 250
    let ok = target.activate(options: [.activateAllWindows])
    if !ok {
        fail("activate_failed", "NSRunningApplication.activate returned false for pid \(target.processIdentifier)")
    }
    let deadline = Date().addingTimeInterval(Double(waitMs) / 1000.0)
    while !target.isActive && Date() < deadline {
        Thread.sleep(forTimeInterval: 0.015)
    }
    jsonOut(ActivateResponse(ok: true, targetPid: target.processIdentifier, previousPid: previous, alreadyActive: false, isActiveNow: target.isActive))
}

func requireAccessibility() {
    if !AXIsProcessTrusted() {
        fail(
            "accessibility_denied",
            "AXIsProcessTrusted() is false. Enable Accessibility for the parent app (e.g. 三月七小助手.app or Terminal.app) in System Settings -> Privacy & Security -> Accessibility.",
            exitCode: 2
        )
    }
}

func postMouse(_ type: CGEventType, at point: CGPoint, button: CGMouseButton = .left, clickState: Int64 = 1, source: CGEventSource?) {
    guard let ev = CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: point, mouseButton: button) else {
        fail("event_create_failed", "Failed to create CGEvent for type \(type.rawValue)")
    }
    ev.setIntegerValueField(.mouseEventClickState, value: clickState)
    ev.post(tap: .cghidEventTap)
}

struct ActionResponse: Codable {
    let ok: Bool
    let action: String
    let details: [String: Double]
}

func runClick(opts: [String: String], flags: Set<String>) -> Never {
    requireAccessibility()
    guard let xStr = opts["x"], let yStr = opts["y"], let x = Double(xStr), let y = Double(yStr) else {
        fail("invalid_args", "click requires --x and --y", exitCode: 64)
    }
    let holdMs = max(5, Int(opts["hold-ms"] ?? "45") ?? 45)
    let isRight = flags.contains("right")
    let isDouble = flags.contains("double")
    let button: CGMouseButton = isRight ? .right : .left
    let downType: CGEventType = isRight ? .rightMouseDown : .leftMouseDown
    let upType: CGEventType = isRight ? .rightMouseUp : .leftMouseUp
    let pt = CGPoint(x: x, y: y)
    let src = CGEventSource(stateID: .hidSystemState)

    postMouse(.mouseMoved, at: pt, button: button, clickState: 0, source: src)
    Thread.sleep(forTimeInterval: 0.018)

    let count = isDouble ? 2 : 1
    for c in 1...count {
        postMouse(downType, at: pt, button: button, clickState: Int64(c), source: src)
        Thread.sleep(forTimeInterval: Double(holdMs) / 1000.0)
        postMouse(upType, at: pt, button: button, clickState: Int64(c), source: src)
        if c < count {
            Thread.sleep(forTimeInterval: 0.05)
        }
    }
    jsonOut(ActionResponse(ok: true, action: "click", details: ["x": x, "y": y, "holdMs": Double(holdMs), "clicks": Double(count)]))
}

func easeInOut(_ t: Double) -> Double {
    return t < 0.5 ? 2.0 * t * t : 1.0 - pow(-2.0 * t + 2.0, 2.0) / 2.0
}

func runDrag(opts: [String: String]) -> Never {
    requireAccessibility()
    guard let x1 = opts["x1"].flatMap(Double.init),
          let y1 = opts["y1"].flatMap(Double.init),
          let x2 = opts["x2"].flatMap(Double.init),
          let y2 = opts["y2"].flatMap(Double.init) else {
        fail("invalid_args", "drag requires --x1 --y1 --x2 --y2", exitCode: 64)
    }
    let durationMs = max(40, Int(opts["duration-ms"] ?? "420") ?? 420)
    let steps = max(4, Int(opts["steps"] ?? "24") ?? 24)
    let preHoldMs = max(10, Int(opts["pre-hold-ms"] ?? "70") ?? 70)
    let postHoldMs = max(10, Int(opts["post-hold-ms"] ?? "80") ?? 80)

    let p1 = CGPoint(x: x1, y: y1)
    let p2 = CGPoint(x: x2, y: y2)
    let src = CGEventSource(stateID: .hidSystemState)

    postMouse(.mouseMoved, at: p1, button: .left, clickState: 0, source: src)
    Thread.sleep(forTimeInterval: 0.02)
    postMouse(.leftMouseDown, at: p1, button: .left, clickState: 1, source: src)
    Thread.sleep(forTimeInterval: Double(preHoldMs) / 1000.0)

    let stepInterval = Double(durationMs) / 1000.0 / Double(steps)
    for i in 1...steps {
        let t = Double(i) / Double(steps)
        let e = easeInOut(t)
        let cx = x1 + (x2 - x1) * e
        let cy = y1 + (y2 - y1) * e
        postMouse(.leftMouseDragged, at: CGPoint(x: cx, y: cy), button: .left, clickState: 1, source: src)
        Thread.sleep(forTimeInterval: stepInterval)
    }

    Thread.sleep(forTimeInterval: Double(postHoldMs) / 1000.0)
    postMouse(.leftMouseUp, at: p2, button: .left, clickState: 1, source: src)

    jsonOut(ActionResponse(ok: true, action: "drag", details: [
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "durationMs": Double(durationMs), "steps": Double(steps),
        "preHoldMs": Double(preHoldMs), "postHoldMs": Double(postHoldMs)
    ]))
}

let keyMap: [String: CGKeyCode] = [
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26,
    "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35,
    "enter": 36, "return": 36, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42,
    ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "tab": 48, "space": 49, "`": 50,
    "backspace": 51, "delete": 51, "esc": 53, "escape": 53,
    "f17": 64, "f18": 79, "f19": 80, "f20": 90,
    "f5": 96, "f6": 97, "f7": 98, "f3": 99, "f8": 100, "f9": 101,
    "f11": 103, "f13": 105, "f16": 106, "f14": 107, "f10": 109, "f12": 111, "f15": 113,
    "home": 115, "pageup": 116, "forwarddelete": 117, "f4": 118, "end": 119, "f2": 120,
    "pagedown": 121, "f1": 122, "left": 123, "right": 124, "down": 125, "up": 126
]

func parseModifiers(_ raw: String?) -> CGEventFlags {
    guard let raw = raw, !raw.isEmpty else { return [] }
    var flags: CGEventFlags = []
    for part in raw.lowercased().split(separator: ",") {
        switch part.trimmingCharacters(in: .whitespaces) {
        case "cmd", "command": flags.insert(.maskCommand)
        case "shift": flags.insert(.maskShift)
        case "alt", "opt", "option": flags.insert(.maskAlternate)
        case "ctrl", "control": flags.insert(.maskControl)
        default: break
        }
    }
    return flags
}

func runKey(opts: [String: String]) -> Never {
    requireAccessibility()
    guard let rawKey = opts["key"] else {
        fail("invalid_args", "key requires --key <name|keycode>", exitCode: 64)
    }
    let lower = rawKey.lowercased()
    let code: CGKeyCode
    if let mapped = keyMap[lower] {
        code = mapped
    } else if let num = UInt16(lower) {
        code = num
    } else {
        fail("unknown_key", "Unknown key name or keycode: \(rawKey)", exitCode: 64)
    }
    let holdMs = max(10, Int(opts["hold-ms"] ?? "40") ?? 40)
    let mods = parseModifiers(opts["modifiers"])
    let src = CGEventSource(stateID: .hidSystemState)
    guard let down = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true),
          let up = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false) else {
        fail("event_create_failed", "Failed to create keyboard CGEvent")
    }
    if !mods.isEmpty {
        down.flags = mods
        up.flags = mods
    }
    down.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: Double(holdMs) / 1000.0)
    up.post(tap: .cghidEventTap)
    jsonOut(ActionResponse(ok: true, action: "key", details: ["keyCode": Double(code), "holdMs": Double(holdMs)]))
}

func runScroll(opts: [String: String]) -> Never {
    requireAccessibility()
    guard let x = opts["x"].flatMap(Double.init),
          let y = opts["y"].flatMap(Double.init),
          let dy = opts["dy"].flatMap(Int32.init) else {
        fail("invalid_args", "scroll requires --x --y --dy", exitCode: 64)
    }
    let dx = opts["dx"].flatMap(Int32.init) ?? 0
    let src = CGEventSource(stateID: .hidSystemState)
    postMouse(.mouseMoved, at: CGPoint(x: x, y: y), button: .left, clickState: 0, source: src)
    Thread.sleep(forTimeInterval: 0.02)
    guard let ev = CGEvent(scrollWheelEvent2Source: src, units: .pixel, wheelCount: 2, wheel1: dy, wheel2: dx, wheel3: 0) else {
        fail("event_create_failed", "Failed to create scroll CGEvent")
    }
    ev.post(tap: .cghidEventTap)
    jsonOut(ActionResponse(ok: true, action: "scroll", details: ["x": x, "y": y, "dx": Double(dx), "dy": Double(dy)]))
}

func runMouseEvent(_ kind: String, opts: [String: String], flags: Set<String>) -> Never {
    requireAccessibility()
    guard let x = opts["x"].flatMap(Double.init),
          let y = opts["y"].flatMap(Double.init) else {
        fail("invalid_args", "\(kind) requires --x and --y", exitCode: 64)
    }
    let isRight = flags.contains("right")
    let button: CGMouseButton = isRight ? .right : .left
    let pt = CGPoint(x: x, y: y)
    let src = CGEventSource(stateID: .hidSystemState)
    let evType: CGEventType
    let clickState: Int64
    switch kind {
    case "mouse-down":
        postMouse(.mouseMoved, at: pt, button: button, clickState: 0, source: src)
        Thread.sleep(forTimeInterval: 0.015)
        evType = isRight ? .rightMouseDown : .leftMouseDown
        clickState = 1
    case "mouse-move":
        evType = flags.contains("drag") ? (isRight ? .rightMouseDragged : .leftMouseDragged) : .mouseMoved
        clickState = flags.contains("drag") ? 1 : 0
    case "mouse-up":
        evType = isRight ? .rightMouseUp : .leftMouseUp
        clickState = 1
    default:
        fail("unknown_command", "Unsupported mouse kind: \(kind)", exitCode: 64)
    }
    postMouse(evType, at: pt, button: button, clickState: clickState, source: src)
    jsonOut(ActionResponse(ok: true, action: kind, details: ["x": x, "y": y]))
}

func runKeyState(_ kind: String, opts: [String: String], keyDown: Bool) -> Never {
    requireAccessibility()
    guard let rawKey = opts["key"] else {
        fail("invalid_args", "\(kind) requires --key <name|keycode>", exitCode: 64)
    }
    let lower = rawKey.lowercased()
    let code: CGKeyCode
    if let mapped = keyMap[lower] {
        code = mapped
    } else if let num = UInt16(lower) {
        code = num
    } else {
        fail("unknown_key", "Unknown key name or keycode: \(rawKey)", exitCode: 64)
    }
    let mods = parseModifiers(opts["modifiers"])
    let src = CGEventSource(stateID: .hidSystemState)
    guard let ev = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: keyDown) else {
        fail("event_create_failed", "Failed to create keyboard CGEvent")
    }
    if !mods.isEmpty {
        ev.flags = mods
    }
    ev.post(tap: .cghidEventTap)
    jsonOut(ActionResponse(ok: true, action: kind, details: ["keyCode": Double(code)]))
}

let (cmd, opts, flags) = parseArgs()
switch cmd {
case "tcc-check":
    runTccCheck()
case "window-info":
    runWindowInfo(opts: opts, flags: flags)
case "activate":
    runActivate(opts: opts)
case "click":
    runClick(opts: opts, flags: flags)
case "mouse-down", "mouse-move", "mouse-up":
    runMouseEvent(cmd, opts: opts, flags: flags)
case "drag":
    runDrag(opts: opts)
case "key":
    runKey(opts: opts)
case "key-down":
    runKeyState("key-down", opts: opts, keyDown: true)
case "key-up":
    runKeyState("key-up", opts: opts, keyDown: false)
case "scroll":
    runScroll(opts: opts)
default:
    fail("unknown_command", "Unknown command: \(cmd)", exitCode: 64)
}
