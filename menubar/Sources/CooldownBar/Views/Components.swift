import SwiftUI

// Tabular number that rolls only its changed digits on refresh (odometer).
struct MetricText: View {
    let value: String
    var size: CGFloat = 15
    var weight: Font.Weight = .regular
    var color: Color = .primary

    var body: some View {
        Text(value)
            .font(Theme.mono(size, weight))
            .foregroundStyle(color)
            .contentTransition(.numericText())
            .animation(.easeOut(duration: 0.28), value: value)
    }
}

// Engraved uppercase micro-label.
struct EngLabel: View {
    let text: String
    var size: CGFloat = 10
    var body: some View {
        Text(text)
            .font(Theme.text(size, .semibold))
            .tracking(0.6)
            .textCase(.uppercase)
            .foregroundStyle(Theme.faint)
    }
}

// Horizontal CPU% meter for hot-process rows.
struct MeterBar: View {
    var fraction: Double      // 0...1 of a full single core
    var color: Color
    var height: CGFloat = 4

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.trough)
                Capsule().fill(color)
                    .frame(width: max(2, geo.size.width * min(1, max(0, fraction))))
            }
        }
        .frame(height: height)
    }
}

struct StatusDot: View {
    var color: Color
    var size: CGFloat = 6
    var body: some View { Circle().fill(color).frame(width: size, height: size) }
}

// .ultraThinMaterial card with a hairline bezel.
struct Card<Content: View>: View {
    var tint: Color? = nil
    @ViewBuilder var content: Content
    var body: some View {
        content
            .background(Theme.panel, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
            .background(
                RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    .fill(tint ?? .clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    .stroke(Theme.cardStroke, lineWidth: 0.5)
            )
    }
}

// MARK: - Formatting helpers

enum Fmt {
    static func bytes(_ n: Int64?) -> String {
        guard let n, n > 0 else { return "—" }
        let g = Double(n) / 1_073_741_824
        if g >= 1 { return String(format: "%.1f GB", g) }
        let m = Double(n) / 1_048_576
        if m >= 1 { return String(format: "%.0f MB", m) }
        return String(format: "%.0f KB", Double(n) / 1024)
    }

    static func duration(_ seconds: Double?) -> String {
        guard let s = seconds, s >= 0 else { return "—" }
        if s < 60 { return "\(Int(s))s" }
        if s < 3600 { return "\(Int(s / 60))m" }
        if s < 86400 { return "\(Int(s / 3600))h" }
        return "\(Int(s / 86400))d"
    }

    /// Port of dashboard.py shorten_cmd: drop the interpreter prefix to its
    /// basename, compact $HOME to ~, and when over budget compress the first
    /// path token's *leading* segments so the script tail stays readable.
    /// Final overflow truncates from the right — the head is the process
    /// identity and must never be eaten by a leading ellipsis.
    static func shortenCmd(name: String?, cmdline: String?, width: Int = 52) -> String {
        let cmd = (cmdline ?? "").trimmingCharacters(in: .whitespaces)
        let parts = cmd.split(separator: " ").map(String.init)
        guard let first = parts.first else { return name ?? "?" }
        let head = first.split(separator: "/").last.map(String.init) ?? first
        let home = ProcessInfo.processInfo.environment["HOME"] ?? ""
        var rest = parts.dropFirst().map { tok -> String in
            var t = tok
            if !home.isEmpty, t.hasPrefix(home) { t = "~" + t.dropFirst(home.count) }
            return t
        }
        var shown = rest.isEmpty ? head : head + " " + rest.joined(separator: " ")
        if shown.count <= width { return shown }

        // Over budget: spend it on the tail of the first absolute-ish path —
        // that's how two `python …/script.py` rows stay distinguishable.
        if let ti = rest.firstIndex(where: { $0.contains("/") }) {
            let otherLen = head.count + 1
                + rest.enumerated().filter { $0.offset != ti }
                    .reduce(0) { $0 + $1.element.count + 1 }
            rest[ti] = shortenPathToken(rest[ti], maxLen: max(8, width - otherLen))
            shown = head + " " + rest.joined(separator: " ")
        }
        if shown.count > width {
            // No compressible path (e.g. WebContent's numeric/--flag args):
            // keep the head, drop the tail.
            shown = String(shown.prefix(width - 1)) + "…"
        }
        return shown
    }

    /// `/a/b/c/d/e/f.py` with budget 12 → `…/e/f.py`. Never fewer than the
    /// last two segments — the parent dir usually identifies the project.
    private static func shortenPathToken(_ path: String, maxLen: Int) -> String {
        if path.count <= maxLen { return path }
        let segs = path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        if segs.count <= 2 { return path }
        var keep = 2
        while keep < segs.count {
            let candidate = "…/" + segs.suffix(keep).joined(separator: "/")
            if candidate.count > maxLen { keep -= 1; break }
            keep += 1
        }
        keep = max(keep, 2)
        return "…/" + segs.suffix(keep).joined(separator: "/")
    }

    /// Status tokens render in Chinese like the rest of the UI; the raw
    /// English level survives only in JSON / accessibility.
    static func pressureZh(_ level: String) -> String {
        switch level {
        case "normal": return "正常"
        case "warn": return "偏高"
        case "critical": return "告警"
        default: return level
        }
    }
}
