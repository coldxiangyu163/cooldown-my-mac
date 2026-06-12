import SwiftUI
import AppKit

// Permission-free visual QA: fetch one live sample, render the popover to a PNG
// via ImageRenderer (no screen-recording entitlement needed). Materials render
// as a flat translucency over the backdrop rather than live blur, which is fine
// for checking layout, type and color. Run with: `CooldownBar render out.png`
// (append `dark` for the dark-appearance variant).
@MainActor
enum RenderShot {
    static func run(path: String) -> Never {
        // ImageRenderer resolves dynamic NSColors against the app appearance,
        // so set both the appearance and the SwiftUI color scheme together.
        let dark = CommandLine.arguments.contains("dark")
        NSApplication.shared.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)

        let store = StatusStore()
        let client = store.client
        do {
            let s = try client.status()
            let t = try? client.thermalDetail()
            store.status = s
            store.thermal = t
            store.dev = (try? client.dev()) ?? []
            store.lastUpdated = Date()
        } catch {
            store.lastError = error.localizedDescription
        }
        let runner = ActionRunner(client: client, store: store)
        if CommandLine.arguments.contains("confirm") {
            runner.confirmReapAll(count: max(1, store.status?.reapableCount ?? 12))
        }

        let content = ZStack {
            Theme.backdrop
            PopoverRootView(store: store, runner: runner, embedScroll: false)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Theme.cardStroke, lineWidth: 0.5))
                .shadow(color: Theme.cardShadow, radius: 24, y: 12)
                .padding(40)
        }
        .frame(width: 460)
        .fixedSize()
        .preferredColorScheme(dark ? .dark : .light)
        .environment(\.colorScheme, dark ? .dark : .light)

        let renderer = ImageRenderer(content: content)
        renderer.scale = 2
        renderer.isOpaque = true

        guard let cg = renderer.cgImage else {
            FileHandle.standardError.write(Data("render: ImageRenderer produced no image\n".utf8))
            exit(3)
        }
        let rep = NSBitmapImageRep(cgImage: cg)
        guard let data = rep.representation(using: .png, properties: [:]) else {
            FileHandle.standardError.write(Data("render: PNG encode failed\n".utf8))
            exit(4)
        }
        do {
            try data.write(to: URL(fileURLWithPath: path))
            print("render: wrote \(path) (\(cg.width)x\(cg.height))")
            exit(0)
        } catch {
            FileHandle.standardError.write(Data("render: write failed — \(error.localizedDescription)\n".utf8))
            exit(5)
        }
    }
}
