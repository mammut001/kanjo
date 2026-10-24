#!/usr/bin/env swift
// 生成 Kanjo 的 1024×1024 应用图标 PNG：深色圆角方底 + 三个 agent 色的 treemap 马赛克。
// 用法：swift make_icon.swift [输出路径，默认 Kanjo.png]
// package.sh 在 Resources/Kanjo.icns 缺失或传 --icon 时调用它，再用 iconutil 生成 .icns。
import AppKit

let output = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "Kanjo.png"
let size = 1024

func color(_ hex: UInt32, alpha: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: alpha)
}

let background = color(0x1C1C1E)
let clay = color(0xD97757)    // Claude Code
let blue = color(0x3E79D6)    // Codex CLI
let violet = color(0x7A6AD8)  // Antigravity CLI

guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                                 bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
      let context = NSGraphicsContext(bitmapImageRep: rep) else {
    fatalError("cannot create bitmap context")
}
rep.size = NSSize(width: size, height: size)  // 1 pt = 1 px，不受屏幕倍率影响

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context
context.imageInterpolation = .high
NSColor.clear.setFill()
NSRect(x: 0, y: 0, width: size, height: size).fill()

// 底板：按 macOS 图标网格，824 pt 的圆角方块居中，四周留 100 pt 给阴影。
let body = NSRect(x: 100, y: 100, width: 824, height: 824)
let bodyPath = NSBezierPath(roundedRect: body, xRadius: 185, yRadius: 185)

NSGraphicsContext.saveGraphicsState()
let shadow = NSShadow()
shadow.shadowColor = NSColor.black.withAlphaComponent(0.35)
shadow.shadowOffset = NSSize(width: 0, height: -10)
shadow.shadowBlurRadius = 24
shadow.set()
background.setFill()
bodyPath.fill()
NSGraphicsContext.restoreGraphicsState()

// 顶部一点点亮，底部一点点暗，让深色底不至于死平。
NSGraphicsContext.saveGraphicsState()
bodyPath.addClip()
NSGradient(starting: NSColor.white.withAlphaComponent(0.06), ending: NSColor.black.withAlphaComponent(0.10))?
    .draw(in: body, angle: -90)
NSGraphicsContext.restoreGraphicsState()

// 细描边，深色桌面上也能看清边界。
NSColor.white.withAlphaComponent(0.10).setStroke()
let rim = NSBezierPath(roundedRect: body.insetBy(dx: 1.5, dy: 1.5), xRadius: 183.5, yRadius: 183.5)
rim.lineWidth = 3
rim.stroke()

// 马赛克：600×600 的区域，自上而下的坐标（和 treemap 的阅读顺序一致），画的时候再翻转。
let area = NSRect(x: 212, y: 212, width: 600, height: 600)
let tiles: [(x: CGFloat, y: CGFloat, w: CGFloat, h: CGFloat, c: NSColor)] = [
    (0,   0,   324, 600, clay),    // 最大的项目
    (352, 0,   248, 316, blue),
    (352, 344, 132, 256, violet),
    (512, 344, 88,  110, clay),
    (512, 482, 88,  118, blue),
]
for t in tiles {
    let rect = NSRect(x: area.minX + t.x, y: area.maxY - t.y - t.h, width: t.w, height: t.h)
    let radius = min(32, min(t.w, t.h) * 0.2)  // 小块圆角跟着缩，避免变成药丸
    t.c.setFill()
    NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius).fill()
}

NSGraphicsContext.restoreGraphicsState()

guard let png = rep.representation(using: .png, properties: [:]) else { fatalError("PNG encoding failed") }
do {
    try png.write(to: URL(fileURLWithPath: output))
} catch {
    FileHandle.standardError.write("cannot write \(output): \(error)\n".data(using: .utf8)!)
    exit(1)
}
print("wrote \(output)")
