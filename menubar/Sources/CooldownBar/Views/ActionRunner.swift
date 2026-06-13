import SwiftUI

// What a diagnosis badge / row does when tapped.
enum DiagAction: Equatable {
    case reapAll(Int)
    case reapKind(String)
    case kill(pid: Int, name: String)
    case purge
    case restoreSleep
}

// Every destructive action is gated: clicking only *arms* a ConfirmChip that
// shows exactly what will run; ⏎ fires. Reap/purge route through `cool` and
// `purge`; kill sends SIGTERM (the same first signal `cool` uses).
@MainActor
@Observable
final class ActionRunner {
    struct Pending: Identifiable {
        let id = UUID()
        let prompt: String
        // Concrete verb shown on the confirm button (终止/回收/清理/恢复).
        let verb: String
        let run: @MainActor () async -> String
    }

    var pending: Pending?
    var lastAction: String?

    private let client: CoolClient
    private let store: StatusStore

    init(client: CoolClient, store: StatusStore) {
        self.client = client
        self.store = store
    }

    func confirmKill(pid: Int, name: String) {
        pending = Pending(prompt: "终止 PID \(pid)（\(name)）？", verb: "终止") { [client] in
            await Task.detached { _ = try? client.shell("/bin/kill", ["-TERM", "\(pid)"]) }.value
            return "已发送 SIGTERM → \(pid)"
        }
    }

    func confirmReap(kind: String) {
        pending = Pending(prompt: "回收闲置的 \(kind) 会话？", verb: "回收") { [client] in
            let out = await Task.detached { (try? client.runText(["reap", "--kinds", kind, "--yes"])) ?? "" }.value
            return Self.lastLine(out) ?? "已回收 \(kind)"
        }
    }

    func confirmReapAll(count: Int) {
        pending = Pending(prompt: "回收 \(count) 个闲置 AI 会话？", verb: "回收") { [client] in
            let out = await Task.detached { (try? client.runText(["reap", "--yes"])) ?? "" }.value
            return Self.lastLine(out) ?? "已回收闲置 AI"
        }
    }

    func confirmPurge() {
        pending = Pending(prompt: "清理闲置内存缓存（需管理员权限）？", verb: "清理") { [client] in
            // Route sudo through the system auth prompt rather than re-implementing escalation.
            await Task.detached {
                _ = try? client.shell("/usr/bin/osascript", ["-e", "do shell script \"purge\" with administrator privileges"])
            }.value
            return "已清理系统缓存"
        }
    }

    func openWatch() {
        guard let bin = client.resolveBinary() else { return }
        let script = "tell application \"Terminal\" to do script \"\(bin) watch\"\ntell application \"Terminal\" to activate"
        Task.detached { [client] in _ = try? client.shell("/usr/bin/osascript", ["-e", script]) }
    }

    func confirmRestoreSleep() {
        pending = Pending(prompt: "恢复 displaysleep / disksleep 默认值？", verb: "恢复") { [client] in
            let out = await Task.detached { (try? client.runText(["thermal", "--restore"])) ?? "" }.value
            return Self.lastLine(out) ?? "已恢复睡眠策略"
        }
    }

    /// Non-destructive: reveal a path in Finder. No confirm chip.
    func revealInFinder(_ path: String) {
        Task.detached { [client] in _ = try? client.shell("/usr/bin/open", [path]) }
        lastAction = "在 Finder 打开 \(((path as NSString).lastPathComponent))"
    }

    /// Dispatch a diagnosis badge's action.
    func perform(_ action: DiagAction) {
        switch action {
        case let .reapAll(n): confirmReapAll(count: n)
        case let .reapKind(k): confirmReap(kind: k)
        case let .kill(pid, name): confirmKill(pid: pid, name: name)
        case .purge: confirmPurge()
        case .restoreSleep: confirmRestoreSleep()
        }
    }

    func fire() {
        guard let p = pending else { return }
        pending = nil
        Task { @MainActor in
            let result = await p.run()
            lastAction = result
            await store.refreshOnce()
            // Let the result linger, then clear.
            try? await Task.sleep(for: .seconds(6))
            if lastAction == result { lastAction = nil }
        }
    }

    func cancel() { pending = nil }

    private static func lastLine(_ s: String) -> String? {
        s.split(whereSeparator: \.isNewline).last.map(String.init)?.trimmingCharacters(in: .whitespaces)
    }
}

extension CoolClient {
    /// Run an arbitrary executable (non-`cool`), ignoring stdout decoding.
    func shell(_ path: String, _ args: [String]) throws -> Data {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: path)
        proc.arguments = args
        let out = Pipe()
        proc.standardOutput = out
        proc.standardError = Pipe()
        try proc.run()
        let data = out.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        return data
    }

    func runText(_ args: [String]) throws -> String {
        let data = try run(args)
        return String(data: data, encoding: .utf8) ?? ""
    }
}

// The armed-action confirmation chip.
struct ConfirmChip: View {
    let runner: ActionRunner
    let pending: ActionRunner.Pending

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 12)).foregroundStyle(Theme.amber)
            Text(pending.prompt).font(Theme.text(12, .medium)).foregroundStyle(.primary).lineLimit(2)
            Spacer(minLength: 6)
            Button { runner.cancel() } label: {
                HStack(spacing: 4) {
                    Text("取消").font(Theme.text(11, .medium)).foregroundStyle(.primary)
                    Text("esc").font(Theme.mono(10)).foregroundStyle(.secondary)
                }
                .padding(.horizontal, 9).padding(.vertical, 4)
                .overlay(Capsule().stroke(Theme.hairline, lineWidth: 1))
            }
            .buttonStyle(.plain).keyboardShortcut(.cancelAction)
            Button { runner.fire() } label: {
                HStack(spacing: 3) { Text(pending.verb).font(Theme.text(12, .semibold)); Image(systemName: "return").font(.system(size: 10)) }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 10).padding(.vertical, 4)
                    .background(Capsule().fill(Theme.red))
            }
            .buttonStyle(.plain).keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        // Floats over scrolling rows: the now-translucent panel alone would let
        // them bleed into the prompt text, so back it with its own material.
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(Theme.amber.opacity(0.45), lineWidth: 1))
        .shadow(color: Theme.cardShadow, radius: 12, y: 5)
        .padding(.horizontal, Theme.outerPad)
        .padding(.bottom, 10)
    }
}
