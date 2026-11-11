# -*- coding: utf-8 -*-
"""生成应用图标 iconset（蓝色圆角方块 + 白色学士帽）。用法: python make_icon.py 输出目录.iconset."""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    pad, radius = 100, 185
    box = (pad, pad, S - pad, S - pad)

    # 阴影
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 14, S - pad, S - pad + 14), radius, fill=(0, 40, 120, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))

    # 渐变底色
    grad = Image.new("RGBA", (S, S))
    top, bottom = (64, 200, 255), (10, 92, 245)
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(top, bottom, y / S) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    img.paste(grad, (0, 0), mask)

    # 学士帽
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    cx, cy = S // 2, 452
    w, h = 300, 130
    # 帽身（帽檐下方的弧形部分）
    d.rounded_rectangle((cx - 175, cy + 40, cx + 175, cy + 205), 60, fill=(235, 244, 255, 255))
    d.ellipse((cx - 175, cy + 150, cx + 175, cy + 260), fill=(235, 244, 255, 255))
    # 菱形帽顶
    d.polygon([(cx, cy - h), (cx + w, cy), (cx, cy + h), (cx - w, cy)], fill=white)
    # 流苏
    blue = (20, 110, 245, 255)
    d.line([(cx, cy), (cx + 215, cy + 50)], fill=blue, width=18)
    d.line([(cx + 215, cy + 50), (cx + 215, cy + 210)], fill=white, width=18)
    d.ellipse((cx + 190, cy + 200, cx + 240, cy + 250), fill=white)
    d.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), fill=blue)

    # 底部进度条
    by = 770
    d.rounded_rectangle((260, by, S - 260, by + 36), 18, fill=(255, 255, 255, 80))
    d.rounded_rectangle((260, by, 600, by + 36), 18, fill=white)
    return img


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    master = make_master()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = size * scale
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            master.resize((px, px), Image.LANCZOS).save(os.path.join(out, name))


if __name__ == "__main__":
    main()
