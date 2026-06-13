import SwiftUI
import AppKit

// Single source of truth for color, type, materials and the CLI-parity
// thresholds. Everything reads from here so color stays a pure signal:
// >85% of the surface is grayscale, accents appear only where a value
// crosses its own threshold — mirroring cooldown/ui/dashboard.py.

extension Color {
    init(hex: UInt32, alpha: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: alpha
        )
    }

    // Appearance-adaptive color — resolves at draw time via NSColor's
    // dynamic provider, so surfaces follow the system light/dark switch
    // without any forced color scheme.
    init(lightHex: UInt32, darkHex: UInt32, lightAlpha: Double = 1, darkAlpha: Double = 1) {
        self.init(nsColor: NSColor(name: nil) { appearance in
            let dark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
            let hex = dark ? darkHex : lightHex
            let alpha = dark ? darkAlpha : lightAlpha
            return NSColor(
                srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255,
                alpha: CGFloat(alpha)
            )
        })
    }
}

enum Theme {
    // Three state accents — matched to the CLI health bands (80 / 55).
    static let green = Color(hex: 0x34C759)   // calm
    static let amber = Color(hex: 0xFF9F0A)   // warn
    static let red   = Color(hex: 0xFF453A)   // critical
    static let cyan  = Color(hex: 0x64D2FF)   // reserved: thermal headroom / "cool"

    static let trough = Color(lightHex: 0x000000, darkHex: 0xFFFFFF, lightAlpha: 0.07, darkAlpha: 0.10)
    static let hairline = Color(lightHex: 0x000000, darkHex: 0xFFFFFF, lightAlpha: 0.08, darkAlpha: 0.10)

    // Tertiary text — hand-tuned instead of .tertiary: the system style drops
    // to ~2.7:1 on the dark panels; these keep 10pt labels ≥4.5:1 everywhere.
    static let faint = Color(lightHex: 0x6E6E76, darkHex: 0x9898A0)

    // Adaptive surfaces — Control Center recipe: cards are *translucent white*
    // over the window material (light: milky glass; dark: white at ~7% — never
    // opaque graphite) so the frosted backdrop reads through every tile.
    static let surface = Color(lightHex: 0xECECEF, darkHex: 0x1C1C20)  // popover base tint (behind cards)
    static let panel = Color(lightHex: 0xFFFFFF, darkHex: 0xFFFFFF, lightAlpha: 0.62, darkAlpha: 0.07)  // card fill
    static let cardStroke = Color(lightHex: 0x000000, darkHex: 0xFFFFFF, lightAlpha: 0.06, darkAlpha: 0.08)
    static let cardShadow = Color(lightHex: 0x000000, darkHex: 0x000000, lightAlpha: 0.07, darkAlpha: 0.45)

    // Top "light catch" on each card — the inset highlight that makes the
    // translucent fill read as glass instead of fog. Near-invisible in light
    // mode by design; carries the depth cue in dark mode.
    static let cardTopHighlight = LinearGradient(
        colors: [Color.white.opacity(0.12), .clear],
        startPoint: .top, endPoint: .center
    )

    // Subtle cool→warm wash so the backdrop isn't a flat gray; dark variant
    // keeps the same hue drift at graphite luminance.
    static let backdrop = LinearGradient(
        colors: [
            Color(lightHex: 0xF3F6FC, darkHex: 0x22242B),
            Color(lightHex: 0xF4F1F8, darkHex: 0x252229),
            Color(lightHex: 0xEFF3F7, darkHex: 0x202428),
        ],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )

    // Corner radii & spacing (pt)
    static let popoverWidth: CGFloat = 380
    static let cardRadius: CGFloat = 12
    static let outerPad: CGFloat = 16
    static let gutter: CGFloat = 10

    // Fonts — every numeral is tabular SF Mono so digits never jitter.
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced).monospacedDigit()
    }
    static func text(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight)
    }
    static func rounded(_ size: CGFloat, _ weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }
}

// Health bands — identical to dashboard.py health_score() color logic.
enum HealthBand {
    case calm, warn, critical

    static func of(score: Int) -> HealthBand {
        if score >= 80 { return .calm }
        if score >= 55 { return .warn }
        return .critical
    }

    var color: Color {
        switch self {
        case .calm: return Theme.green
        case .warn: return Theme.amber
        case .critical: return Theme.red
        }
    }
}

enum Palette {
    // _pct_color(pct): >=90 red, >=75 amber, >=50 cyan, else green.
    static func pct(_ pct: Double) -> Color {
        if pct >= 90 { return Theme.red }
        if pct >= 75 { return Theme.amber }
        if pct >= 50 { return Theme.cyan }
        return Theme.green
    }

    // idle_color(seconds): >=1800 red(reapable), >=600 amber, >=60 cyan, else green.
    static func idle(_ seconds: Double) -> Color {
        if seconds >= 1800 { return Theme.red }
        if seconds >= 600 { return Theme.amber }
        if seconds >= 60 { return Theme.cyan }
        return Theme.green
    }

    // Battery cell temp: >=40 red, >=35 amber, else green (battery panel scale).
    static func batteryTemp(_ c: Double) -> Color {
        if c >= 40 { return Theme.red }
        if c >= 35 { return Theme.amber }
        return Theme.green
    }

    // hot_procs per-core color: cpu_percent * ncpu -> >=80 red, >=40 amber,
    // else green — same as the CLI table, so hot-proc meters speak the same
    // heat language as every other bar instead of reading as empty gray.
    static func perCore(_ perCorePct: Double) -> Color {
        if perCorePct >= 80 { return Theme.red }
        if perCorePct >= 40 { return Theme.amber }
        return Theme.green
    }

    // KIND_COLORS (dashboard.py) mapped from terminal names to native hex.
    static let kind: [String: Color] = [
        "claude": Color(hex: 0xFF6FD8),      // bright_magenta
        "droid": Color(hex: 0x0A84FF),       // bright_blue
        "hermes": Color(hex: 0x64D2FF),      // bright_cyan
        "codex": Color(hex: 0x30D158),       // bright_green
        "gemini": Color(hex: 0x5E9EFF),      // blue
        "copilot": Color(hex: 0xFFD60A),     // bright_yellow
        "cursor-agent": Color(hex: 0x64D2FF),// cyan
        "windsurf": Color(hex: 0xFF6FD8),
        "continue": Color(hex: 0xCB6FE6),    // magenta
        "amp": Color(hex: 0xCB6FE6),
        "aider": Color(hex: 0xFF453A),       // red
        "opencode": Color(hex: 0xFF453A),    // bright_red
        "crush": Color(hex: 0xFF453A),
        "nanobot": Color(hex: 0xFFD60A),
        "qwen": Color(hex: 0xFFD60A),        // yellow
        "kimi": Color(hex: 0xFFD60A),
        "goose": Color(hex: 0xF2F2F7),       // bright_white
        "aichat": Color(hex: 0xD1D1D6),      // white
        "tmux": Color(hex: 0x64D2FF, alpha: 0.4),  // dim cyan
        "cmux": Color(hex: 0x64D2FF, alpha: 0.4),
        "zellij": Color(hex: 0x64D2FF, alpha: 0.4),
    ]

    static func kindColor(_ kindName: String?) -> Color {
        guard let k = kindName else { return Theme.amber }
        return Self.kind[k] ?? Theme.amber
    }
}

// "Why this score" — recompute the same penalties dashboard.py applies, so
// the hero scrub legend is honest rather than a vibe.
struct Penalty: Identifiable {
    let id = UUID()
    let label: String
    let points: Int   // negative
}

enum HealthBreakdown {
    static func penalties(_ s: Status) -> [Penalty] {
        var out: [Penalty] = []
        let m = s.memory
        switch m.pressureLevel {
        case "critical": out.append(Penalty(label: "MEM pressure critical", points: -25))
        case "warn": out.append(Penalty(label: "MEM pressure warn", points: -12))
        default:
            if m.usedPercent >= 90 { out.append(Penalty(label: "MEM \(Int(m.usedPercent))%", points: -25)) }
            else if m.usedPercent >= 80 { out.append(Penalty(label: "MEM \(Int(m.usedPercent))%", points: -12)) }
        }
        if let st = m.swapTotal, st > 0, let su = m.swapUsed, Double(su) / Double(st) > 0.5 {
            out.append(Penalty(label: "SWAP > 50%", points: -15))
        }
        let cpu = s.system.cpuPercent
        if cpu >= 80 { out.append(Penalty(label: "CPU \(Int(cpu))%", points: -15)) }
        else if cpu >= 60 { out.append(Penalty(label: "CPU \(Int(cpu))%", points: -6)) }
        if let w = s.thermal.thermalWarning, w != "none" {
            out.append(Penalty(label: "THERMAL \(w)", points: -20))
        }
        if s.thermal.sleepPrevented == true, (s.thermal.displaySleep ?? 0) == 0 {
            out.append(Penalty(label: "sleep blocked", points: -5))
        }
        if let t = s.battery?.tempC {
            if t >= 45 { out.append(Penalty(label: "BATT \(Int(t))°C", points: -20)) }
            else if t >= 40 { out.append(Penalty(label: "BATT \(Int(t))°C", points: -10)) }
            else if t >= 35 { out.append(Penalty(label: "BATT \(Int(t))°C", points: -3)) }
        }
        return out.sorted { $0.points < $1.points }
    }
}
