import SwiftUI

// MARK: - Derived data for the rich popover

struct ProjectRollup: Identifiable {
    let name: String
    let rss: Int64
    let count: Int
    let launchers: [String]
    let root: String?
    var id: String { name }
}

struct Diagnosis: Identifiable {
    let id = UUID()
    let icon: String
    let title: String
    let detail: String
    let color: Color
    var action: DiagAction? = nil   // tappable when set
}

extension Status {
    func projectRollups(_ dev: [DevProc]) -> [ProjectRollup] {
        var map: [String: (Int64, Int, Set<String>, String?)] = [:]
        for d in dev {
            let name = d.project?.name ?? "?"
            var e = map[name] ?? (0, 0, [], nil)
            e.0 += d.rss ?? 0
            e.1 += 1
            if let l = d.launcher?.kind { e.2.insert(l) }
            if e.3 == nil { e.3 = d.project?.root }
            map[name] = e
        }
        return map.map { ProjectRollup(name: $0.key, rss: $0.value.0, count: $0.value.1, launchers: $0.value.2.sorted(), root: $0.value.3) }
            .sorted { $0.rss > $1.rss }
    }

    var heaviestProc: Proc? { procs.max { ($0.rss ?? 0) < ($1.rss ?? 0) } }

    func diagnoses(_ dev: [DevProc]) -> [Diagnosis] {
        var out: [Diagnosis] = []
        // CPU on fire → tap to kill the runaway pid
        if let h = hotProcs.first(where: { ($0.cpuPercent ?? 0) * Double(ncpu) >= 80 }) {
            out.append(Diagnosis(icon: "flame.fill", title: "CPU 烤机",
                detail: "\(Fmt.shortenCmd(name: h.name, cmdline: h.cmdline, width: 16)) \(Int((h.cpuPercent ?? 0) * Double(ncpu)))%",
                color: Theme.red, action: .kill(pid: h.pid, name: h.name ?? "?")))
        }
        // Reapable idle AI → tap to reap all
        let reap = reapableCount
        if reap > 0 {
            out.append(Diagnosis(icon: "arrow.3.trianglepath", title: "可回收",
                detail: "\(reap) 个闲置 AI 会话", color: Theme.amber, action: .reapAll(reap)))
        }
        // Memory hog → tap to kill the heaviest pid
        if let p = heaviestProc, let rss = p.rss, rss > 200 * 1_048_576 {
            out.append(Diagnosis(icon: "cube.box.fill", title: "内存大户",
                detail: "\(p.kind ?? p.name ?? "?") · \(Fmt.bytes(rss))", color: .secondary,
                action: .kill(pid: p.pid, name: p.kind ?? p.name ?? "?")))
        }
        // Orphans (informational — no safe bulk action)
        let orphans = dev.filter { $0.isOrphan == true }.count
        if orphans > 0 {
            out.append(Diagnosis(icon: "questionmark.circle.fill", title: "孤儿进程",
                detail: "\(orphans) 个挂在 launchd", color: Theme.amber))
        }
        // Memory pressure → tap to purge
        switch memory.pressureLevel {
        case "critical": out.append(Diagnosis(icon: "memorychip.fill", title: "内存压力", detail: "告警 · \(Int(memory.usedPercent))%", color: Theme.red, action: .purge))
        case "warn": out.append(Diagnosis(icon: "memorychip.fill", title: "内存压力", detail: "偏高 · \(Int(memory.usedPercent))%", color: Theme.amber, action: .purge))
        default: break
        }
        // Body temperature (informational) — silent below the 35°C warn threshold
        if let t = battery?.tempC, t >= 35 {
            out.append(Diagnosis(icon: "thermometer.medium", title: t >= 40 ? "发烧" : "偏热",
                detail: String(format: "电池 %.0f°C", t), color: Palette.batteryTemp(t)))
        }
        // Sleep blocked → tap to restore default sleep policy
        if thermal.sleepPrevented == true, (thermal.displaySleep ?? 0) == 0 {
            // pmset only reports the boolean, not the owning assertion, so say
            // what the value means instead of echoing a token that truncates.
            out.append(Diagnosis(icon: "moon.zzz.fill", title: "睡眠被阻止", detail: "屏幕不休眠",
                color: Theme.amber, action: .restoreSleep))
        }
        return Array(out.prefix(6))
    }

    /// A witty, data-driven real-world comparison for the AI memory footprint.
    var wittyLine: String {
        let gb = Double(totalAIRSS) / 1_073_741_824
        let tabs = max(1, Int(Double(totalAIRSS) / 1_048_576 / 100))   // ~100 MB per Chrome tab
        if gb >= 1 {
            return "≈ 同时开 \(tabs) 个 Chrome 标签 🐘 · 够风扇响一整天 🌀"
        }
        return "还算克制 · 风扇暂时安静 🍃"
    }
}

// MARK: - Hero card

struct HeroCard: View {
    let s: Status

    // Both gradient stops must come from the current band — a calm hero never bleeds red.
    private var bandColors: [Color] {
        switch HealthBand.of(score: s.healthScore) {
        case .calm: return [Theme.cyan, Theme.green]
        case .warn: return [Color(hex: 0xFFC83C), Theme.amber]
        case .critical: return [Color(hex: 0xFF7066), Theme.red]
        }
    }

    var body: some View {
        let heat = LinearGradient(colors: bandColors, startPoint: .leading, endPoint: .trailing)
        Card {
            VStack(alignment: .leading, spacing: 6) {
                // No corner badge: the proc count already headlines below in 48pt.
                HStack(spacing: 5) {
                    Image(systemName: "sparkles").font(.system(size: 11)).foregroundStyle(bandColors[0])
                    EngLabel(text: "现状")
                }
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("\(s.procs.count)")
                        .font(Theme.mono(48, .semibold))
                        .foregroundStyle(heat)
                        .contentTransition(.numericText())
                        .animation(.easeOut(duration: 0.3), value: s.procs.count)
                    Text("个 AI 进程").font(Theme.text(13)).foregroundStyle(.secondary)
                }
                Text("\(Fmt.bytes(s.totalAIRSS)) 被 AI / MCP 进程吃掉")
                    .font(Theme.text(13, .medium)).foregroundStyle(.primary)
                Text("💡 \(s.wittyLine)")
                    .font(Theme.text(11)).foregroundStyle(.secondary).lineLimit(2)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                LinearGradient(colors: [bandColors[0].opacity(0.10), bandColors[1].opacity(0.08)],
                               startPoint: .topLeading, endPoint: .bottomTrailing)
            )
        }
    }
}

// MARK: - Stat chips

struct StatChips: View {
    let s: Status
    var body: some View {
        HStack(spacing: 6) {
            chip("健康", "\(s.healthScore)", HealthBand.of(score: s.healthScore).color)
            chip("CPU", "\(Int(s.system.cpuPercent))%", Palette.pct(s.system.cpuPercent))
            chip("内存", Fmt.pressureZh(s.memory.pressureLevel), s.memory.pressureLevel == "normal" ? Theme.green : (s.memory.pressureLevel == "warn" ? Theme.amber : Theme.red))
            if let t = s.battery?.tempC { chip("电池", "\(Int(t))°", Palette.batteryTemp(t)) }
        }
    }

    private func chip(_ label: String, _ value: String, _ color: Color) -> some View {
        VStack(spacing: 2) {
            EngLabel(text: label, size: 10)
            Text(value).font(Theme.mono(14, .medium)).foregroundStyle(color).lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 7)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).stroke(Theme.cardStroke, lineWidth: 0.5))
    }
}

// MARK: - Diagnosis badges (gamified)

struct DiagnosisGrid: View {
    let items: [Diagnosis]
    let runner: ActionRunner
    @State private var hovered: UUID?   // bool/ID state only — no animated transforms on hover

    var body: some View {
        VStack(spacing: 6) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, pair in
                HStack(spacing: 6) {
                    ForEach(pair) { badge($0) }
                    if pair.count == 1 { Color.clear.frame(maxWidth: .infinity) }
                }
            }
        }
    }

    // chunk into rows of 2 (no LazyVGrid — crash-safe in MenuBarExtra)
    private var rows: [[Diagnosis]] {
        stride(from: 0, to: items.count, by: 2).map { Array(items[$0..<min($0 + 2, items.count)]) }
    }

    // Actionable → real Button with hover highlight; informational → plain container
    // (a disabled Button reads as "dimmed, disabled" to VoiceOver).
    @ViewBuilder
    private func badge(_ d: Diagnosis) -> some View {
        if let a = d.action {
            Button { runner.perform(a) } label: {
                badgeBody(d, highlighted: hovered == d.id)
            }
            .buttonStyle(.plain)
            .onHover { hovered = $0 ? d.id : nil }
            .accessibilityLabel("\(d.title)，\(d.detail)")
        } else {
            badgeBody(d, highlighted: false)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("\(d.title)，\(d.detail)")
        }
    }

    private func badgeBody(_ d: Diagnosis, highlighted: Bool) -> some View {
        HStack(spacing: 8) {
            Image(systemName: d.icon)
                .font(.system(size: 13))
                .foregroundStyle(d.color)
                .frame(width: 26, height: 26)
                .background(d.color.opacity(0.14), in: RoundedRectangle(cornerRadius: 7, style: .continuous))
            VStack(alignment: .leading, spacing: 1) {
                Text(d.title).font(Theme.text(12, .medium)).foregroundStyle(.primary).lineLimit(1)
                Text(d.detail).font(Theme.mono(10)).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            if d.action != nil {
                Image(systemName: "chevron.right").font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.faint)
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(highlighted ? Color.primary.opacity(0.06) : .clear,
                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
            .stroke(d.action != nil ? d.color.opacity(0.35) : Theme.cardStroke, lineWidth: 0.5))
    }
}

// MARK: - Per-core load chart

struct CoreLoadChart: View {
    let perCpu: [Double]
    let topology: String?

    var body: some View {
        let peak = perCpu.enumerated().max { $0.element < $1.element }
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                EngLabel(text: "核心负载")
                Spacer()
                if let pk = peak {
                    Text("峰值 #\(pk.offset) \(Int(pk.element))%").font(Theme.mono(10)).foregroundStyle(Theme.faint)
                }
            }
            HStack(alignment: .bottom, spacing: 3) {
                ForEach(Array(perCpu.enumerated()), id: \.offset) { _, v in
                    Capsule()
                        .fill(Palette.pct(v))
                        .frame(maxWidth: .infinity)
                        .frame(height: max(3, CGFloat(v) / 100 * 42 + 3))
                }
            }
            .frame(height: 46, alignment: .bottom)
            if let topo = topology {
                Text(topo).font(Theme.mono(10)).foregroundStyle(Theme.faint)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous).stroke(Theme.cardStroke, lineWidth: 0.5))
    }
}

// MARK: - Ranking bars (AI families + projects)

struct RankRow: Identifiable {
    let dot: Color?
    let label: String
    let sublabel: String?
    let value: Int64
    let trailing: String
    let barColor: Color
    var action: (@MainActor () -> Void)? = nil
    var actionLabel: String? = nil
    var hoverNote: String? = nil   // actionless rows explain themselves on hover
    // Keyed by label (unique per card) so hover survives the 12s data refresh.
    var id: String { label }
}

struct RankBars: View {
    let title: String
    let icon: String
    let rows: [RankRow]
    @State private var hovered: String?

    var body: some View {
        let maxV = max(1, rows.map(\.value).max() ?? 1)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 5) {
                EngLabel(text: title)
                Image(systemName: icon).font(.system(size: 10)).foregroundStyle(Theme.faint)
            }
            ForEach(rows) { r in
                let hover = hovered == r.id
                let active = r.action != nil && hover
                VStack(alignment: .leading, spacing: 3) {
                    // fixed header height — hover pill must never grow the row (window size is pinned)
                    HStack(spacing: 6) {
                        if let dot = r.dot { StatusDot(color: dot, size: 7) }
                        Text(r.label).font(Theme.text(12, .medium)).foregroundStyle(.primary).lineLimit(1)
                        Spacer(minLength: 6)
                        Text(r.trailing).font(Theme.mono(11)).foregroundStyle(.secondary)
                        if active, let al = r.actionLabel, let act = r.action {
                            Button(action: act) {
                                Text(al).font(Theme.text(10, .semibold)).foregroundStyle(Theme.cyan)
                                    .padding(.horizontal, 6)
                                    .frame(height: 15)
                                    .background(Theme.cyan.opacity(0.12), in: Capsule())
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("\(al)，\(r.label)")
                        } else if hover, r.action == nil, let note = r.hoverNote {
                            // Plain faint text, no pill/highlight: explains *why* there
                            // is nothing to do here instead of ignoring the hover.
                            Text(note).font(Theme.text(10)).foregroundStyle(Theme.faint)
                                .frame(height: 15).lineLimit(1)
                        }
                    }
                    .frame(height: 16)
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(Theme.trough)
                            Capsule().fill(r.barColor.opacity(0.85))
                                .frame(width: max(3, geo.size.width * CGFloat(Double(r.value) / Double(maxV))))
                        }
                    }
                    .frame(height: 5)
                    if let sub = r.sublabel {
                        Text(sub).font(Theme.mono(10)).foregroundStyle(Theme.faint).lineLimit(1)
                    }
                }
                .padding(.vertical, 3)
                .padding(.horizontal, 4)
                .background(active ? Color.primary.opacity(0.06) : .clear,
                            in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                .contentShape(Rectangle())
                .onHover { hovered = $0 ? r.id : nil }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous).stroke(Theme.cardStroke, lineWidth: 0.5))
    }
}
