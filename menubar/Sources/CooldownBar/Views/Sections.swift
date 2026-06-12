import SwiftUI

// MARK: - Derived metrics (parity with the CLI)

let AI_KINDS: Set<String> = [
    "droid","codex","claude","opencode","nanobot","hermes","gemini","aider",
    "cursor-agent","copilot","windsurf","qwen","kimi","goose","aichat",
    "continue","amp","crush",
]

struct Family: Identifiable {
    let kind: String
    let count: Int
    let rss: Int64
    let cpu: Double
    let maxIdle: Double
    var id: String { kind }
}

extension Status {
    var ncpu: Int { max(1, system.cpuCountLogical ?? 1) }

    var onFire: Bool {
        hotProcs.contains { ($0.cpuPercent ?? 0) * Double(ncpu) >= 80 }
    }

    var reapableCount: Int {
        procs.filter { p in
            guard let k = p.kind, AI_KINDS.contains(k) else { return false }
            return (p.idleSeconds ?? 0) > 1800
        }.count
    }

    var totalAIRSS: Int64 { procs.reduce(0) { $0 + ($1.rss ?? 0) } }

    var families: [Family] {
        var map: [String: (Int, Int64, Double, Double)] = [:]
        for p in procs {
            let k = p.kind ?? "?"
            var e = map[k] ?? (0, 0, 0, 0)
            e.0 += 1
            e.1 += p.rss ?? 0
            e.2 += p.cpuPercent ?? 0
            e.3 = max(e.3, p.idleSeconds ?? 0)
            map[k] = e
        }
        return map.map { Family(kind: $0.key, count: $0.value.0, rss: $0.value.1, cpu: $0.value.2, maxIdle: $0.value.3) }
            .sorted { $0.rss > $1.rss }
    }
}

// MARK: - On Fire (hot processes)

struct OnFireView: View {
    let s: Status
    let runner: ActionRunner
    @State private var hovered: Int? = nil
    @State private var expanded: Set<Int> = []

    var body: some View {
        let rows = Array(s.hotProcs.prefix(3))
        let anyFire = s.onFire
        Card(tint: anyFire ? Theme.red.opacity(0.06) : nil) {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    EngLabel(text: anyFire ? "着火 · 热进程" : "热进程")
                    Spacer()
                    if anyFire { Image(systemName: "flame.fill").font(.system(size: 10)).foregroundStyle(Theme.red) }
                }
                if rows.isEmpty {
                    Text("当前没有进程在烧 CPU").font(Theme.text(12)).foregroundStyle(Theme.faint)
                }
                ForEach(rows) { h in row(h) }
            }
            .padding(10)
        }
    }

    private func row(_ h: HotProc) -> some View {
        let perCore = (h.cpuPercent ?? 0) * Double(s.ncpu)
        let color = Palette.perCore(perCore)
        let fire = perCore >= 80
        let isExpanded = expanded.contains(h.pid)
        return VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 4) {
                        Text(Fmt.shortenCmd(name: h.name, cmdline: h.cmdline, width: 40))
                            .font(Theme.mono(12))
                            .foregroundStyle(.primary)
                            .lineLimit(1)
                        if fire { Image(systemName: "flame.fill").font(.system(size: 10)).foregroundStyle(Theme.red) }
                    }
                    MeterBar(fraction: perCore / 100, color: color)
                }
                Spacer(minLength: 6)
                VStack(alignment: .trailing, spacing: 2) {
                    MetricText(value: String(format: "%.0f%%", h.cpuPercent ?? 0), size: 13, weight: fire ? .semibold : .regular, color: color)
                    Text("\(Fmt.bytes(h.rss)) · \(Fmt.duration(h.age))").font(Theme.mono(10)).foregroundStyle(Theme.faint)
                }
                // Kill lives only on this button; always present at low opacity
                // so it stays discoverable without a hover hunt.
                Button { runner.confirmKill(pid: h.pid, name: h.name ?? "?") } label: {
                    Image(systemName: "xmark.octagon").font(.system(size: 12)).foregroundStyle(Theme.red)
                }
                .buttonStyle(.plain)
                .opacity(hovered == h.pid ? 1 : 0.3)
                .accessibilityLabel("结束进程 \(h.name ?? "?")")
            }
            if isExpanded {
                Text(Fmt.shortenCmd(name: h.name, cmdline: h.cmdline, width: 200))
                    .font(Theme.mono(10))
                    .foregroundStyle(.secondary)
                    .lineLimit(nil)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .padding(.vertical, 1)
        .background(fire ? Theme.red.opacity(0.06) : .clear)
        .contentShape(Rectangle())
        // Tap toggles cmdline detail. No animation: an animated height change
        // inside MenuBarExtra(.window) re-enters AppKit window layout.
        .onTapGesture {
            if expanded.contains(h.pid) { expanded.remove(h.pid) } else { expanded.insert(h.pid) }
        }
        .onHover { isOn in withAnimation(.easeOut(duration: 0.12)) { hovered = isOn ? h.pid : nil } }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(h.name ?? "?")，CPU \(Int(h.cpuPercent ?? 0))%，内存 \(Fmt.bytes(h.rss))")
    }
}

// MARK: - Action footer

struct ActionFooterView: View {
    let store: StatusStore
    let runner: ActionRunner
    @State private var hoverReap = false

    var body: some View {
        let s = store.status
        let reapable = s?.reapableCount ?? 0
        VStack(spacing: 6) {
            Divider().overlay(Theme.hairline)
            HStack(spacing: 8) {
                Button { runner.confirmReapAll(count: reapable) } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "arrow.3.trianglepath").font(.system(size: 11))
                        Text("回收闲置 AI").font(Theme.text(12, .medium))
                        // Amber badge: red is reserved for destructive confirms.
                        Text("\(reapable)").font(Theme.mono(10, .semibold))
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(Capsule().fill(reapable > 0 ? Theme.amber.opacity(0.9) : Color.secondary.opacity(0.3)))
                            .foregroundStyle(.white)
                    }
                    .padding(.horizontal, 12).padding(.vertical, 6)
                    .background(Theme.panel, in: Capsule())
                    .overlay(Capsule().stroke(Theme.cardStroke, lineWidth: 0.5))
                }
                .buttonStyle(.plain)
                .disabled(reapable == 0)
                .help(reapable > 0 ? "将回收 \(reapable) 个闲置进程" : "没有可回收的闲置进程")
                .accessibilityLabel("回收闲置 AI，共 \(reapable) 个")

                Spacer(minLength: 0)

                iconButton("memorychip", help: "清理内存 (sudo purge)") { runner.confirmPurge() }
                iconButton("waveform.path.ecg", help: "打开 cool watch") { runner.openWatch() }
                iconButton("arrow.clockwise", help: "刷新") { Task { await store.refreshOnce() } }
            }
            provenance(s)
        }
    }

    private func iconButton(_ name: String, help: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: name).font(.system(size: 13)).foregroundStyle(.secondary)
                .frame(width: 28, height: 24)
                .background(Theme.panel, in: RoundedRectangle(cornerRadius: 7, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous).stroke(Theme.cardStroke, lineWidth: 0.5))
        }
        .buttonStyle(.plain)
        .help(help)
        .accessibilityLabel(help)
    }

    private func provenance(_ s: Status?) -> some View {
        let host = s?.host
        let parts = [host?.machine, host?.macos.map { "macOS \($0)" }, s?.system.topology].compactMap { $0 }
        let age = store.lastUpdated.map { "\(Fmt.duration(-$0.timeIntervalSinceNow)) 前采样" } ?? "—"
        return HStack(spacing: 6) {
            Circle().fill(Theme.green).frame(width: 5, height: 5)
            Text((parts + [age]).joined(separator: " · "))
                .font(Theme.mono(10)).foregroundStyle(Theme.faint).lineLimit(1)
            Spacer(minLength: 0)
            if let last = runner.lastAction {
                Text(last).font(Theme.mono(10)).foregroundStyle(.secondary).lineLimit(1)
            }
        }
    }
}
