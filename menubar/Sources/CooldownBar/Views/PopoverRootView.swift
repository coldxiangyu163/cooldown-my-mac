import SwiftUI

struct PopoverRootView: View {
    let store: StatusStore
    let runner: ActionRunner
    var embedScroll: Bool = true   // false → natural height (preview / render)

    var body: some View {
        VStack(spacing: 0) {
            HeaderBar(store: store, runner: runner)
            Divider().overlay(Theme.hairline)

            if let s = store.status {
                // Fixed-height scroll area → the MenuBarExtra window keeps a
                // stable size (content/hover changes never resize the window,
                // which is what triggered the constraint-cycle crashes).
                if embedScroll {
                    ScrollView { content(s) }
                        .frame(height: 500)
                        // Bottom fade hints there is more content below the fold.
                        // Pure overlay — never affects layout / window size.
                        .overlay(alignment: .bottom) {
                            LinearGradient(
                                colors: [Theme.surface.opacity(0), Theme.surface.opacity(0.85)],
                                startPoint: .top, endPoint: .bottom
                            )
                            .frame(height: 24)
                            .allowsHitTesting(false)
                        }
                } else {
                    content(s)
                }

                Divider().overlay(Theme.hairline)
                ActionFooterView(store: store, runner: runner)
                    .padding(.horizontal, Theme.outerPad)
                    .padding(.vertical, 10)
            } else if let e = store.lastError {
                errorState(e)
            } else {
                loadingState
            }
        }
        .frame(width: Theme.popoverWidth)
        // Control-Center style backing: system material for the frosted depth,
        // plus a faint adaptive surface tint so cards keep their hairline
        // separation in both appearances. No forced color scheme — Theme
        // surfaces resolve per-appearance.
        .background(Theme.surface.opacity(0.35))
        .background(.regularMaterial)
        .overlay(alignment: .bottom) {
            if let p = runner.pending {
                ConfirmChip(runner: runner, pending: p)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.9), value: runner.pending?.id)
        .task { store.start() }
    }

    @ViewBuilder private func content(_ s: Status) -> some View {
        VStack(spacing: Theme.gutter) {
            HeroCard(s: s)
            StatChips(s: s)
            diagnosisSection(s)
            // When hot, the actionable hit list jumps above the ranking sections.
            if s.onFire { OnFireView(s: s, runner: runner) }
            if let pc = s.system.perCpu, !pc.isEmpty {
                CoreLoadChart(perCpu: pc, topology: s.system.topology)
            }
            familySection(s)
            projectSection(s)
            if !s.onFire { OnFireView(s: s, runner: runner) }
        }
        .padding(.horizontal, Theme.outerPad)
        .padding(.vertical, 12)
    }

    @ViewBuilder private func diagnosisSection(_ s: Status) -> some View {
        let items = s.diagnoses(store.dev)
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                EngLabel(text: "诊断 · \(items.count)")
                DiagnosisGrid(items: items, runner: runner)
            }
        }
    }

    @ViewBuilder private func familySection(_ s: Status) -> some View {
        let fams = Array(s.families.prefix(5))
        if !fams.isEmpty {
            RankBars(title: "AI CLI 家族", icon: "cpu", rows: fams.map(familyRow))
        }
    }

    private func familyRow(_ f: Family) -> RankRow {
        let isAI = AI_KINDS.contains(f.kind)
        let reapable = isAI && f.maxIdle > 1800   // cool reap's own threshold
        var act: (@MainActor () -> Void)? = nil
        if reapable { act = { runner.confirmReap(kind: f.kind) } }
        // Rows that offer no 回收 say why on hover instead of staying mute.
        let note: String? = reapable ? nil
            : (isAI ? "闲置 \(Fmt.duration(f.maxIdle)) · 满 30m 可回收" : "非 AI 会话 · 不参与回收")
        return RankRow(dot: Palette.kindColor(f.kind), label: f.kind, sublabel: nil, value: f.rss,
                       trailing: "\(f.count) · \(Fmt.bytes(f.rss)) · \(Int(f.cpu))%",
                       barColor: Palette.kindColor(f.kind),
                       action: act, actionLabel: reapable ? "♻ 回收" : nil, hoverNote: note)
    }

    @ViewBuilder private func projectSection(_ s: Status) -> some View {
        let projs = Array(s.projectRollups(store.dev).prefix(5))
        if !projs.isEmpty {
            RankBars(title: "项目占用", icon: "eye", rows: projs.map(projectRow))
        }
    }

    private func projectRow(_ p: ProjectRollup) -> RankRow {
        var act: (@MainActor () -> Void)? = nil
        if let root = p.root { act = { runner.revealInFinder(root) } }
        return RankRow(dot: nil, label: p.name,
                       sublabel: p.launchers.isEmpty ? nil : p.launchers.joined(separator: ", "),
                       value: p.rss, trailing: Fmt.bytes(p.rss),
                       barColor: p.rss > 3 * 1_073_741_824 ? Theme.red : Theme.cyan,
                       action: act, actionLabel: p.root != nil ? "Finder ↗" : nil)
    }

    private var loadingState: some View {
        VStack(spacing: 10) {
            ProgressView().controlSize(.small)
            Text("正在采样…（首次约 8 秒）").font(Theme.text(12)).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity).padding(40)
    }

    private func errorState(_ e: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Theme.amber)
                Text("无法读取 cool").font(Theme.text(14, .semibold))
            }
            Text(e).font(Theme.text(12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Divider()
            HStack {
                Button("重试") { Task { await store.refreshOnce() } }
                Spacer()
                Button("退出") { NSApplication.shared.terminate(nil) }
            }
            .font(Theme.text(12))
        }
        .padding(Theme.outerPad)
        .frame(width: Theme.popoverWidth)
    }
}

struct HeaderBar: View {
    let store: StatusStore
    let runner: ActionRunner

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "snowflake").font(.system(size: 13, weight: .medium)).foregroundStyle(Theme.cyan)
            VStack(alignment: .leading, spacing: 0) {
                Text("Coolant").font(Theme.rounded(13, .semibold)).foregroundStyle(.primary)
                Text("Mac 退烧 · 进程归因").font(Theme.text(10)).foregroundStyle(Theme.faint)
            }
            Spacer()
            // Watch/refresh/timestamp live in the footer — header stays brand + quit only.
            icon("power") { NSApplication.shared.terminate(nil) }
                .accessibilityLabel("退出 Coolant")
        }
        .padding(.horizontal, Theme.outerPad)
        .padding(.vertical, 10)
    }

    private func icon(_ name: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: name).font(.system(size: 12)).foregroundStyle(.secondary).frame(width: 22, height: 22)
        }
        .buttonStyle(.plain)
    }
}
