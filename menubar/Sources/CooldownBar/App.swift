import SwiftUI
import AppKit

// Entry point. `selftest` runs a one-shot decode against the live `cool`
// binary and exits — lets us verify the data layer headlessly, without a GUI.
@main
struct EntryPoint {
    static func main() {
        if CommandLine.arguments.contains("selftest") {
            SelfTest.run()   // exits the process
        }
        if let i = CommandLine.arguments.firstIndex(of: "render"), i + 1 < CommandLine.arguments.count {
            let path = CommandLine.arguments[i + 1]
            MainActor.assumeIsolated { RenderShot.run(path: path) }   // exits
        }
        if CommandLine.arguments.contains("preview") {
            PreviewApp.main()   // popover in a normal window, for visual QA
            return
        }
        CooldownApp.main()
    }
}

@MainActor
final class AppModel {
    let store: StatusStore
    let runner: ActionRunner

    init() {
        let s = StatusStore()
        store = s
        runner = ActionRunner(client: s.client, store: s)
        store.start()   // poll from launch so the bar item is live before the popover opens
    }
}

// Last-good-sample cache. The first live sample takes ~8s; replaying the raw
// `cool status --json` payload from disk lets the popover open with stale data
// instead of a blank loading state. Corrupt cache is deleted, never fatal.
enum StatusCache {
    static let url: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support", isDirectory: true)
        return base.appendingPathComponent("Coolant/status.json", isDirectory: false)
    }()

    // Mirrors CoolClient's decoding so the cached payload parses identically.
    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    /// Returns (status, file mtime), or nil. Undecodable files are removed.
    static func load() -> (Status, Date?)? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        guard let s = try? decoder.decode(Status.self, from: data) else {
            try? FileManager.default.removeItem(at: url)
            return nil
        }
        let mtime = (try? FileManager.default.attributesOfItem(atPath: url.path))?[.modificationDate] as? Date
        return (s, mtime)
    }

    static func save(_ raw: Data) {
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? raw.write(to: url, options: .atomic)
    }
}

@MainActor
@Observable
final class StatusStore {
    var status: Status?
    var thermal: ThermalDetail?
    var dev: [DevProc] = []
    var lastError: String?
    var lastUpdated: Date?
    // `cool status --json` samples ~all processes and takes several seconds, so
    // a menu bar tool must poll lazily — not every few seconds like the TUI.
    var refreshInterval: TimeInterval = 12
    var barImage: NSImage?   // pre-rendered menu bar item; never rendered inside a view body

    let client = CoolClient()
    private var task: Task<Void, Never>?

    func start() {
        guard task == nil else { return }
        // Stale-but-instant: seed from the on-disk cache so the popover and bar
        // icon show real numbers immediately; lastUpdated = file mtime so the
        // footer's sampled-ago honestly reflects the data's age.
        if status == nil, let (cached, mtime) = StatusCache.load() {
            status = cached
            lastUpdated = mtime
        }
        updateBarImage()   // ring immediately, before the first (slow) live sample lands
        task = Task { [weak self] in
            var tick = 0
            while !Task.isCancelled {
                // CPU/GPU die temp changes slowly and needs a second subprocess;
                // refresh it only every 6th tick, status every tick.
                await self?.refreshOnce(fetchThermal: tick % 6 == 0)
                tick += 1
                let interval = self?.refreshInterval ?? 12
                try? await Task.sleep(for: .seconds(interval))
            }
        }
    }

    func stop() { task?.cancel(); task = nil }

    func refreshOnce(fetchThermal: Bool = true) async {
        let client = self.client
        let wantThermal = fetchThermal
        let result: Result<(Status, ThermalDetail?, [DevProc]?), Error> = await Task.detached(priority: .utility) {
            do {
                let (s, raw) = try client.statusWithRaw()
                StatusCache.save(raw)   // off the main actor, with the sample still hot
                let t = wantThermal ? (try? client.thermalDetail()) : nil
                let d = try? client.dev()
                return .success((s, t, d))
            } catch {
                return .failure(error)
            }
        }.value

        switch result {
        case let .success((s, t, d)):
            status = s
            if let t { thermal = t }   // keep last reading on ticks we skipped thermal
            if let d { dev = d }
            lastError = nil
            lastUpdated = Date()
            updateBarImage()
        case let .failure(err):
            lastError = err.localizedDescription
            updateBarImage()
        }
    }

    // Render the snowflake + temperature to an NSImage HERE (main actor, but
    // outside any view-graph update) so the menu bar label never runs an
    // ImageRenderer inside its own body — that re-enters AppKit's constraint
    // cycle and can crash when the popover window lays out.
    private func updateBarImage() {
        let hasStatus = status != nil
        // Calm (and pre-sample) renders monochrome as a template image so the
        // system tints it for light/dark menu bars; in template mode only the
        // alpha channel matters, so hierarchy is expressed via black + opacity.
        // Only warn/critical/onFire earns a colored, non-template image.
        // Pre-sample (~8s) shows the snowflake dimmed rather than a fallback symbol.
        let template = barIsCalm
        let iconColor: Color = template
            ? .black.opacity(hasStatus ? 1.0 : 0.45)
            : barColor
        let textColor: Color = template ? .black.opacity(0.62) : Color(nsColor: .secondaryLabelColor)

        let content = HStack(spacing: 3) {
            Image(systemName: "snowflake")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(iconColor)
            if let t = glanceTemp.map({ Int($0.rounded()) }) {
                Text("\(t)")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(textColor)
            }
        }
        .padding(.horizontal, 1)
        .frame(height: 16)

        let renderer = ImageRenderer(content: content)
        renderer.scale = 2
        if let img = renderer.nsImage {
            img.isTemplate = template
            barImage = img
        }
    }

    /// Template-eligible: nothing crossed a threshold, so the bar item carries
    /// no information through color. Mirrors barColor's red conditions exactly.
    private var barIsCalm: Bool {
        guard let s = status else { return true }   // neutral pre-sample ring
        if s.onFire
            || (s.thermal.thermalWarning ?? "none") != "none"
            || s.memory.pressureLevel == "critical"
            || (s.battery?.tempC ?? 0) >= 45 {
            return false
        }
        return HealthBand.of(score: s.healthScore) == .calm
    }

    /// Glanceable temperature: prefer CPU die temp; fall back to battery temp.
    var glanceTemp: Double? {
        thermal?.smc?.cpuDieTemp ?? status?.battery?.tempC
    }

    /// Bar item color: red when something is actually wrong, else the health band.
    var barColor: Color {
        guard let s = status else { return .secondary }
        if s.onFire
            || (s.thermal.thermalWarning ?? "none") != "none"
            || s.memory.pressureLevel == "critical"
            || (s.battery?.tempC ?? 0) >= 45 {
            return Theme.red
        }
        return HealthBand.of(score: s.healthScore).color
    }
}

struct CooldownApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        MenuBarExtra {
            PopoverRootView(store: model.store, runner: model.runner)
        } label: {
            BarLabel(store: model.store)
        }
        .menuBarExtraStyle(.window)
    }
}

// Snowflake + temperature in the menu bar. MenuBarExtra renders a SwiftUI label
// as a template image (monochrome); when calm we lean into that (template
// NSImage, system-tinted), but to keep accent color on warn/critical the image
// must stay non-template and be presented with .original rendering.
struct BarLabel: View {
    let store: StatusStore

    var body: some View {
        if let img = store.barImage {
            Image(nsImage: img)
                .renderingMode(img.isTemplate ? .template : .original)
                .accessibilityLabel(axLabel)
        } else {
            Image(systemName: "snowflake")
                .accessibilityLabel(axLabel)
        }
    }

    private var axLabel: String {
        guard let s = store.status else { return "Coolant：正在采样" }
        return "Coolant：健康 \(s.healthScore) 分"
    }
}

// Visual-QA harness: renders the popover inside a normal resizable window over
// a desktop-like backdrop so the Liquid Glass materials have something to pick
// up. Launch with `CooldownBar preview`.
struct PreviewApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup("Coolant Preview") {
            ZStack {
                Theme.backdrop
                    .ignoresSafeArea()
                PopoverRootView(store: model.store, runner: model.runner)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Theme.cardStroke, lineWidth: 0.5))
                    .shadow(color: Theme.cardShadow, radius: 24, y: 12)
                    .padding(40)
            }
            .frame(width: 460, height: 720)
        }
        .windowResizability(.contentSize)
    }
}
