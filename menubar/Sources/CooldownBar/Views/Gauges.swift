import SwiftUI

// Menu-bar health ring (rendered off-tree by StatusStore.updateBarImage).
// Geometry is rock-still; only `color` reports state.
struct HealthRing: View {
    var fraction: Double          // 0...1 fill
    var color: Color
    var lineWidth: CGFloat = 2.5

    var body: some View {
        ZStack {
            Circle()
                .stroke(Theme.trough, lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: max(0.0001, min(1, fraction)))
                .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
        }
        .padding(lineWidth / 2)
        .aspectRatio(1, contentMode: .fit)
    }
}
