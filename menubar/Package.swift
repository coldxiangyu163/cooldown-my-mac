// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "CooldownBar",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "CooldownBar",
            swiftSettings: [
                .swiftLanguageMode(.v5)
            ]
        )
    ]
)
