#!/usr/bin/env python3
"""生成 Windows 用的图标（.ico）：应用图标 + 托盘图标（正常 / 出错）。

应用图标直接用 Mac 的 1024×1024 `ui/Resources/Kanjo.png`（同一份美术，不重画），
转成 16–256 的多尺寸 .ico。

托盘图标是 **Kanjo 标志本身**（深色圆角方块 + treemap 马赛克，和 app 图标同一套颜色），
不是 Mac 菜单栏那种 SF Symbol 单色字形——Windows 托盘不能给模板图自动反色，一个细线条
字形在 16px 上会糊成一个色点，而实心方块在深色 / 浅色任务栏上都看得清。
每个尺寸单独画（不是把 256 缩下去）：16 / 20 / 24 只画 3 块马赛克，32 以上画完整 5 块，
这样 100% / 125% / 150% DPI 下都不会变成一团。

出错时在右下角加红点（Mac 是 exclamationmark.triangle，托盘上没有文字，红点是最省的表达）。

只在本机跑（需要 Pillow）：

    python3 windows/scripts/make-icons.py

产物：
    windows/src/Kanjo.App/Assets/Kanjo.ico      应用图标 / exe 资源图标
    windows/src/Kanjo.App/Assets/Tray.ico       托盘图标（正常）
    windows/src/Kanjo.App/Assets/TrayError.ico  托盘图标（出错，带红点）
"""

import io
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ASSETS = os.path.join(REPO, "windows", "src", "Kanjo.App", "Assets")
SOURCE = os.path.join(REPO, "ui", "Resources", "Kanjo.png")

# 应用图标：Windows 会在标题栏、任务栏、Alt+Tab、资源管理器里各取一档。
APP_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# 托盘图标：Windows 实际用 16 / 20 / 24 / 32（100 / 125 / 150 / 200 %），高分屏会再放大取用。
TRAY_SIZES = [16, 20, 24, 32, 48, 64, 256]

# 和 app 图标（ui/Resources/make_icon.swift）同一套颜色。
BACKGROUND = (0x1C, 0x1C, 0x1E, 0xFF)
CLAY = (0xD9, 0x77, 0x57, 0xFF)    # Claude Code
BLUE = (0x3E, 0x79, 0xD6, 0xFF)    # Codex CLI
VIOLET = (0x7A, 0x6A, 0xD8, 0xFF)  # Antigravity CLI
ERROR_RED = (0xD9, 0x3B, 0x3B, 0xFF)

SUPERSAMPLE = 4


def draw_mark(size, error=False):
    """在 size×size 上画 Kanjo 标志：深色圆角方块 + 马赛克（+ 出错红点）。

    小尺寸（16 / 20 / 24）单独排版：只留 1px 外边距、块尽量大，这样 100 / 125 / 150 % DPI
    下也是三块分明的颜色，而不是一团橙色。32px 以上才用 app 图标那 5 块的完整布局。
    """
    scale = SUPERSAMPLE
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # 圆角方块：几乎占满画布（托盘里没有留白可比），半径约 22%。
    radius = max(2, round(canvas * 0.22))
    draw.rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=radius, fill=BACKGROUND)

    # 小尺寸留白更少、缝更细，块才够大。
    small = size <= 24
    inset = round(canvas * (0.10 if small else 0.15))
    area = canvas - inset * 2
    gap = max(1, round(canvas * (0.045 if small else 0.05)))

    def tile(x, y, w, h, color):
        left = inset + round(area * x)
        top = inset + round(area * y)
        right = inset + round(area * (x + w)) - gap
        bottom = inset + round(area * (y + h)) - gap
        if right <= left or bottom <= top:
            return
        r = max(1, round(min(right - left, bottom - top) * 0.22))
        draw.rounded_rectangle((left, top, right, bottom), radius=r, fill=color)

    if small:
        # 三块：左大块 + 右上 + 右下（更多就糊成一片了）。
        tile(0.00, 0.00, 0.53, 1.00, CLAY)
        tile(0.565, 0.00, 0.435, 0.47, BLUE)
        tile(0.565, 0.515, 0.435, 0.485, VIOLET)
    else:
        # 32 以上：和 app 图标一样的 5 块。
        tile(0.00, 0.00, 0.54, 1.00, CLAY)
        tile(0.57, 0.00, 0.43, 0.52, BLUE)
        tile(0.57, 0.55, 0.20, 0.45, VIOLET)
        tile(0.80, 0.55, 0.20, 0.20, CLAY)
        tile(0.80, 0.78, 0.20, 0.22, BLUE)

    if error:
        # 右下角红点，外面留一圈背景色，避免和蓝色块贴在一起看不清。
        dot = round(canvas * 0.38)
        ring = max(1, round(canvas * 0.07))
        right = canvas - round(canvas * 0.04)
        bottom = canvas - round(canvas * 0.04)
        box = (right - dot, bottom - dot, right, bottom)
        draw.ellipse(
            (box[0] - ring, box[1] - ring, box[2] + ring, box[3] + ring), fill=BACKGROUND
        )
        draw.ellipse(box, fill=ERROR_RED)

    return image.resize((size, size), Image.LANCZOS)


def write_ico(path, images):
    """手写 ICO 容器：每个尺寸放自己那张 PNG（Windows Vista 起支持 PNG 压缩的条目）。

    Pillow 的 `save(sizes=...)` 只会从最大那张往下缩，那样 16px 就又变成一团糊；
    这里每档尺寸都是单独画好的位图。
    """
    import struct

    payloads = []
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        payloads.append(buffer.getvalue())

    header = struct.pack("<HHH", 0, 1, len(images))
    # 目录项 16 字节：宽、高、调色板数、保留、色平面、位深、数据长度、数据偏移
    offset = 6 + 16 * len(images)
    entries = b""
    for image, payload in zip(images, payloads):
        width, height = image.size
        entries += struct.pack(
            "<BBBBHHII",
            width if width < 256 else 0,
            height if height < 256 else 0,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        offset += len(payload)

    with open(path, "wb") as handle:
        handle.write(header + entries)
        for payload in payloads:
            handle.write(payload)


def make_app_icon():
    src = Image.open(SOURCE).convert("RGBA")
    out = os.path.join(ASSETS, "Kanjo.ico")
    # 应用图标沿用 Mac 那张 1024 图（各尺寸从它高质量缩放），和之前的产物一致。
    images = [src.resize(size, Image.LANCZOS) for size in APP_SIZES]
    write_ico(out, images)
    print("wrote", out)


def make_tray_icons():
    for name, error in (("Tray.ico", False), ("TrayError.ico", True)):
        out = os.path.join(ASSETS, name)
        # 每个尺寸单独画：小尺寸只有 3 块马赛克，大尺寸才是完整 5 块。
        write_ico(out, [draw_mark(size, error) for size in TRAY_SIZES])
        print("wrote", out)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    make_app_icon()
    make_tray_icons()


if __name__ == "__main__":
    main()
