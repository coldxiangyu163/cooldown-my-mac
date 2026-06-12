import Foundation

// Thin bridge over the `cool` CLI. The menu bar app owns no collection logic:
// it shells out to `cool <cmd> --json` and decodes. This keeps a single source
// of truth (the Python collectors) and means the bar can never disagree with
// `cool status` in the terminal.

enum CoolError: Error, LocalizedError {
    case binaryNotFound
    case nonZeroExit(code: Int32, stderr: String)
    case emptyOutput

    var errorDescription: String? {
        switch self {
        case .binaryNotFound:
            return "找不到 cool 命令。请用 pipx 安装 cooldown-my-mac，或在设置里指定 cool 路径。"
        case let .nonZeroExit(code, stderr):
            return "cool 退出码 \(code): \(stderr.trimmingCharacters(in: .whitespacesAndNewlines))"
        case .emptyOutput:
            return "cool 没有任何输出。"
        }
    }
}

struct CoolClient: Sendable {
    /// Caller-supplied override (from Settings); otherwise auto-resolved.
    var explicitPath: String?

    private static let candidatePaths: [String] = {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return [
            ProcessInfo.processInfo.environment["COOL_BIN"],
            "\(home)/.local/bin/cool",          // pipx default
            "/opt/homebrew/bin/cool",           // Homebrew (Apple Silicon)
            "/usr/local/bin/cool",              // Homebrew (Intel) / manual
            "/usr/bin/cool",
        ].compactMap { $0 }
    }()

    func resolveBinary() -> String? {
        let fm = FileManager.default
        let all = ([explicitPath].compactMap { $0 }) + Self.candidatePaths
        for path in all where fm.isExecutableFile(atPath: path) {
            return path
        }
        // GUI apps don't inherit the interactive shell PATH; ask a login shell
        // where `cool` is (covers pipx/homebrew installs not in our candidates).
        return Self.resolveViaLoginShell()
    }

    private static func resolveViaLoginShell() -> String? {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/zsh")
        proc.arguments = ["-lc", "command -v cool"]
        let out = Pipe()
        proc.standardOutput = out
        proc.standardError = Pipe()
        do { try proc.run() } catch { return nil }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        let path = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return (!path.isEmpty && FileManager.default.isExecutableFile(atPath: path)) ? path : nil
    }

    /// Run `cool <args>` and return raw stdout. Blocking; call off the main thread.
    func run(_ args: [String]) throws -> Data {
        guard let bin = resolveBinary() else { throw CoolError.binaryNotFound }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: bin)
        proc.arguments = args

        let out = Pipe()
        let err = Pipe()
        proc.standardOutput = out
        proc.standardError = err

        try proc.run()
        let data = out.fileHandleForReading.readDataToEndOfFile()
        let errData = err.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()

        if proc.terminationStatus != 0 {
            let stderr = String(data: errData, encoding: .utf8) ?? ""
            throw CoolError.nonZeroExit(code: proc.terminationStatus, stderr: stderr)
        }
        if data.isEmpty { throw CoolError.emptyOutput }
        return data
    }

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    func decode<T: Decodable>(_ type: T.Type, from args: [String]) throws -> T {
        let data = try run(args)
        return try Self.decoder.decode(T.self, from: data)
    }

    func status() throws -> Status { try decode(Status.self, from: ["status", "--json"]) }

    /// Like `status()` but also hands back the raw JSON so callers can persist
    /// the exact payload — lossless vs. re-encoding the decoded model.
    func statusWithRaw() throws -> (Status, Data) {
        let data = try run(["status", "--json"])
        return (try Self.decoder.decode(Status.self, from: data), data)
    }

    func thermalDetail() throws -> ThermalDetail { try decode(ThermalDetail.self, from: ["thermal", "--json"]) }
    func dev() throws -> [DevProc] { try decode([DevProc].self, from: ["dev", "--json"]) }
}
