import Foundation

// Codable mirrors of `cool ... --json`. Property names are camelCase;
// decoding uses `.convertFromSnakeCase`, so `health_score` -> healthScore, etc.
// Every field the CLI may emit as null is modelled Optional so a degraded
// machine (Intel, SMC unavailable, no battery) decodes without throwing.

struct Status: Codable, Sendable {
    let healthScore: Int
    let host: Host
    let system: SystemInfo
    let memory: Memory
    let thermal: Thermal
    let battery: Battery?
    let procs: [Proc]
    let hotProcs: [HotProc]
}

struct Host: Codable, Sendable {
    let node: String?
    let machine: String?
    let macos: String?
}

struct SystemInfo: Codable, Sendable {
    let cpuPercent: Double
    let cpuCountLogical: Int?
    let cpuCountPhysical: Int?
    let load1: Double?
    let load5: Double?
    let load15: Double?
    let uptime: Double?
    let totalProcesses: Int?
    let perCpu: [Double]?
    let topology: String?
}

struct Memory: Codable, Sendable {
    let total: Int64
    let used: Int64
    let available: Int64
    let usedPercent: Double
    let wired: Int64?
    let compressed: Int64?
    let swapTotal: Int64?
    let swapUsed: Int64?
    let pageSize: Int64?
    let pressureLevel: String   // "normal" | "warn" | "critical"
}

struct Thermal: Codable, Sendable {
    let thermalWarning: String?     // "none" | ...
    let cpuPowerStatus: String?     // "normal" | ...
    let lowPowerMode: Bool?
    let acPower: Bool?
    let batteryPercent: Int?
    let displaySleep: Int?
    let diskSleep: Int?
    let sleepPrevented: Bool?
}

struct Battery: Codable, Sendable {
    let percent: Double?
    let cycleCount: Int?
    let tempC: Double?
    let healthPercent: Double?
    let condition: String?
    let charging: Bool?
    let acAttached: Bool?
}

struct Proc: Codable, Sendable, Identifiable {
    let pid: Int
    let ppid: Int?
    let kind: String?
    let name: String?
    let cmdline: String?
    let rss: Int64?
    let cpuPercent: Double?
    let createTime: Double?
    let age: Double?
    let tty: String?
    let user: String?
    let idleSeconds: Double?

    var id: Int { pid }
}

struct HotProc: Codable, Sendable, Identifiable {
    let pid: Int
    let name: String?
    let cmdline: String?
    let cpuPercent: Double?
    let rss: Int64?
    let user: String?
    let createTime: Double?
    let age: Double?

    var id: Int { pid }
}

// `cool dev --json` — per-process dev-stack inventory with project + launcher
// attribution. Used for the "项目占用排行" ranking bars.
struct DevProc: Codable, Sendable {
    let pid: Int
    let lang: String?
    let framework: String?
    let rss: Int64?
    let cpuPercent: Double?
    let isOrphan: Bool?
    let project: Proj?
    let launcher: Launcher?

    struct Proj: Codable, Sendable {
        let root: String?
        let name: String?
    }
    struct Launcher: Codable, Sendable {
        let kind: String?
        let label: String?
    }
}

// `cool thermal --json` — only needed for CPU/GPU die temps + fan, which
// `cool status` does not carry. SMC is often "unavailable" (no readings).
struct ThermalDetail: Codable, Sendable {
    let smc: SMC?

    struct SMC: Codable, Sendable {
        let source: String?
        let cpuDieTemp: Double?
        let gpuDieTemp: Double?
        let fanRpm: Double?
        let cpuPowerW: Double?
        let gpuPowerW: Double?
        let packagePowerW: Double?
    }
}
