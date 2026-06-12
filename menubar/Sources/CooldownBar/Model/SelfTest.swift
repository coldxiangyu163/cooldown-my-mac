import Foundation

// Headless verification of the data layer: fetch + decode once, print a
// summary, exit non-zero on any failure. Run with: `CooldownBar selftest`.
enum SelfTest {
    static func run() -> Never {
        let client = CoolClient()
        guard let bin = client.resolveBinary() else {
            FileHandle.standardError.write(Data("selftest: cool binary not found\n".utf8))
            exit(2)
        }
        print("selftest: using cool at \(bin)")
        do {
            let s = try client.status()
            let t = try? client.thermalDetail()
            let temp = t?.smc?.cpuDieTemp ?? s.battery?.tempC
            print("  health_score : \(s.healthScore)")
            print("  cpu          : \(String(format: "%.1f", s.system.cpuPercent))%  topo=\(s.system.topology ?? "?")")
            print("  memory       : \(String(format: "%.1f", s.memory.usedPercent))%  pressure=\(s.memory.pressureLevel)")
            print("  thermal      : warning=\(s.thermal.thermalWarning ?? "?")  cpuPower=\(s.thermal.cpuPowerStatus ?? "?")")
            print("  battery      : \(s.battery?.percent.map { String(format: "%.0f", $0) } ?? "n/a")%  temp=\(s.battery?.tempC.map { String(format: "%.1f", $0) } ?? "n/a")°C")
            print("  glance temp  : \(temp.map { String(format: "%.1f", $0) } ?? "n/a")°C  (smc source=\(t?.smc?.source ?? "n/a"))")
            print("  ai procs     : \(s.procs.count)")
            print("  hot procs    : \(s.hotProcs.count)  hottest=\(s.hotProcs.first?.name ?? "none") @ \(String(format: "%.0f", s.hotProcs.first?.cpuPercent ?? 0))%")
            if let dev = try? client.dev() {
                let byProj = Dictionary(grouping: dev) { $0.project?.name ?? "?" }
                let top = byProj.map { (name: $0.key, rss: $0.value.reduce(Int64(0)) { $0 + ($1.rss ?? 0) }) }
                    .sorted { $0.rss > $1.rss }.first
                print("  dev procs    : \(dev.count)  projects=\(byProj.count)  top=\(top?.name ?? "?") (\(((top?.rss ?? 0)) / 1_048_576)MB)")
            }
            print("selftest: OK")
            exit(0)
        } catch {
            FileHandle.standardError.write(Data("selftest: FAILED — \(error.localizedDescription)\n".utf8))
            exit(1)
        }
    }
}
