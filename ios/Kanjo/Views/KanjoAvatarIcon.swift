import SwiftUI

struct KanjoAvatarIcon: View {
    var size: CGFloat = 64

    private let clay = Color(red: 0xD9 / 255.0, green: 0x77 / 255.0, blue: 0x57 / 255.0)
    private let blue = Color(red: 0x3E / 255.0, green: 0x79 / 255.0, blue: 0xD6 / 255.0)
    private let violet = Color(red: 0x7A / 255.0, green: 0x6A / 255.0, blue: 0xD8 / 255.0)

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.22, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            Color(red: 0x24 / 255.0, green: 0x24 / 255.0, blue: 0x28 / 255.0),
                            Color(red: 0x14 / 255.0, green: 0x14 / 255.0, blue: 0x16 / 255.0)
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .overlay(
                    RoundedRectangle(cornerRadius: size * 0.22, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.12), lineWidth: max(0.5, size * 0.015))
                )

            let areaSize = size * (600.0 / 1024.0)
            let s = areaSize / 600.0

            Canvas { ctx, _ in
                let tiles: [(x: CGFloat, y: CGFloat, w: CGFloat, h: CGFloat, c: Color)] = [
                    (0,   0,   324, 600, clay),
                    (352, 0,   248, 316, blue),
                    (352, 344, 132, 256, violet),
                    (512, 344, 88,  110, clay),
                    (512, 482, 88,  118, blue),
                ]
                for t in tiles {
                    let rx = t.x * s
                    let ry = t.y * s
                    let rw = t.w * s
                    let rh = t.h * s
                    let r = min(32, min(t.w, t.h) * 0.2) * s
                    let path = Path(roundedRect: CGRect(x: rx, y: ry, width: rw, height: rh),
                                    cornerRadius: max(1.0, r),
                                    style: .continuous)
                    ctx.fill(path, with: .color(t.c))
                }
            }
            .frame(width: areaSize, height: areaSize)
        }
        .frame(width: size, height: size)
    }
}
