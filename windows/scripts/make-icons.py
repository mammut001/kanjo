#!/usr/bin/env python3
"""生成 Windows 用的图标（.ico）：应用图标 + 托盘图标（正常 / 出错）。

应用图标直接用 Mac 的 1024×1024 `ui/Resources/Kanjo.png`（同一份美术，不重画），
转成 16–256 的多尺寸 .ico；托盘图标按 `TrayIconFactory` 里的画法（圆圈 + 十字笔）重画，
放大到 256 再缩出各档尺寸，这样 16px 的托盘里也是清晰的像素而不是缩糊的位图。

只在本机跑（需要 Pillow）：

    python3 windows/scripts/make-icons.py

产物：
    windows/src/Kanjo.App/Assets/Kanjo.ico      应用图标 / exe 资源图标
    windows/src/Kanjo.App/Assets/Tray.ico       托盘图标（正常，陶土色，深浅任务栏都看得见）
    windows/src/Kanjo.App/Assets/TrayError.ico  托盘图标（出错，红色）
"""

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ASSETS = os.path.join(REPO, "windows", "src", "Kanjo.App", "Assets")
SOURCE = os.path.join(REPO, "ui", "Resources", "Kanjo.png")

# 应用图标：Windows 会在标题栏、任务栏、Alt+Tab、资源管理器里各取一档。
APP_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# 托盘图标：Windows 用 16 / 20 / 24 / 32，高分屏会再放大取用。
TRAY_SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)]

# 和 Mac 的 agent 色一致：Claude Code 的陶土色（深浅任务栏上都够对比），出错用红。
TRAY_NORMAL = (0xD9, 0x77, 0x57, 0xFF)
TRAY_ERROR = (0xD9, 0x3B, 0x3B, 0xFF)


def make_app_icon():
    src = Image.open(SOURCE).convert("RGBA")
    out = os.path.join(ASSETS, "Kanjo.ico")
    src.save(out, format="ICO", sizes=APP_SIZES)
    print("wrote", out)


def draw_tray(color):
    """256×256 上按 TrayIconFactory 的比例画，再交给 Pillow 缩到各档。"""
    scale = 8  # 32 → 256
    size = 32 * scale
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    center = size / 2
    ring = 12 * scale
    width = 2.4 * scale
    draw.ellipse(
        (center - ring, center - ring, center + ring, center + ring),
        outline=color,
        width=round(width),
    )
    bar = 2.4 * scale
    half = 7 * scale  # 14 长
    draw.rectangle((center - bar / 2, center - half, center + bar / 2, center + half), fill=color)
    draw.rectangle((center - half, center - bar / 2, center + half, center + bar / 2), fill=color)
    return image


def make_tray_icons():
    for name, color in (("Tray.ico", TRAY_NORMAL), ("TrayError.ico", TRAY_ERROR)):
        out = os.path.join(ASSETS, name)
        draw_tray(color).save(out, format="ICO", sizes=TRAY_SIZES)
        print("wrote", out)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    make_app_icon()
    make_tray_icons()


if __name__ == "__main__":
    main()
