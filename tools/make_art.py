#!/usr/bin/env python3
"""Generate addon artwork (Catppuccin Macchiato + Mauve). Needs Pillow."""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.join(os.path.dirname(__file__), "..", "addons")
BASE, MANTLE, CRUST = (36, 39, 58), (30, 32, 48), (24, 25, 38)
SURFACE0, TEXT = (54, 58, 79), (202, 211, 245)
MAUVE, LAVENDER, BLUE = (198, 160, 246), (183, 189, 248), (138, 173, 244)
SS = 3  # supersampling factor


def headphones(d, cx, cy, r, w, color, cup=(1.0, 1.7)):
    """Headband arc and two ear cups centred on (cx, cy)."""
    box = [cx - r, cy - r, cx + r, cy + r]
    d.arc(box, 180, 360, fill=color, width=w)
    cw, ch = int(w * cup[0] * 1.5), int(w * cup[1] * 1.9)
    for side in (-1, 1):
        x = cx + side * (r - w // 2)
        d.rounded_rectangle([x - cw // 2, cy - ch // 8, x + cw // 2, cy + ch], radius=cw // 2, fill=color)
    d.ellipse([cx - r, cy - w // 2 - 1, cx - r + w, cy + w // 2], fill=color)
    d.ellipse([cx + r - w, cy - w // 2 - 1, cx + r, cy + w // 2], fill=color)


def bars(d, cx, cy, heights, bw, gap, color):
    total = len(heights) * bw + (len(heights) - 1) * gap
    x = cx - total // 2
    for h in heights:
        d.rounded_rectangle([x, cy - h // 2, x + bw, cy + h // 2], radius=bw // 2, fill=color)
        x += bw + gap


def icon_base(size):
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BASE)
    d.rounded_rectangle([s * 0.03, s * 0.03, s * 0.97, s * 0.97], radius=int(s * 0.19), outline=SURFACE0, width=SS * 3)
    return img, d, s


def addon_icon(path, size=512):
    img, d, s = icon_base(size)
    headphones(d, s // 2, int(s * 0.50), int(s * 0.27), int(s * 0.07), MAUVE)
    bars(d, s // 2, int(s * 0.50), [int(s * f) for f in (0.10, 0.20, 0.30, 0.20, 0.10)], int(s * 0.03), int(s * 0.025), LAVENDER)
    # sync arrows ring under the headphones
    ring = [s * 0.36, s * 0.66, s * 0.64, s * 0.94]
    d.arc(ring, 200, 340, fill=BLUE, width=int(s * 0.025))
    d.arc(ring, 20, 160, fill=BLUE, width=int(s * 0.025))
    for ang, sign in ((340, 1), (160, 1)):
        cx, cy = (ring[0] + ring[2]) / 2, (ring[1] + ring[3]) / 2
        rad = (ring[2] - ring[0]) / 2
        x, y = cx + rad * math.cos(math.radians(ang)), cy + rad * math.sin(math.radians(ang))
        t = math.radians(ang + 90)
        a = int(s * 0.04)
        d.polygon([(x + a * math.cos(t), y + a * math.sin(t)),
                   (x - a * math.cos(t), y - a * math.sin(t)),
                   (x + a * 1.6 * math.cos(t + math.pi / 2), y + a * 1.6 * math.sin(t + math.pi / 2))], fill=BLUE)
    img.resize((size, size), Image.LANCZOS).save(path)


def repo_icon(path, size=512):
    img, d, s = icon_base(size)
    for i, color in enumerate((SURFACE0, LAVENDER, MAUVE)):
        y = s * (0.30 + i * 0.17)
        d.rounded_rectangle([s * 0.22, y, s * 0.78, y + s * 0.12], radius=int(s * 0.04), fill=color)
        d.ellipse([s * 0.68, y + s * 0.035, s * 0.68 + s * 0.05, y + s * 0.035 + s * 0.05], fill=BASE)
    img.resize((size, size), Image.LANCZOS).save(path)


def fanart(path, w=1920, h=1080):
    img = Image.new("RGB", (w, h), MANTLE)
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        c = tuple(int(MANTLE[i] * (1 - t) + CRUST[i] * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    headphones(gd, int(w * 0.72), int(h * 0.52), 330, 70, MAUVE + (70,))
    bars(gd, int(w * 0.72), int(h * 0.50), [90, 190, 300, 190, 90], 30, 24, LAVENDER + (60,))
    glow = glow.filter(ImageFilter.GaussianBlur(2))
    img.paste(glow, (0, 0), glow)
    img.save(path, quality=88)


if __name__ == "__main__":
    a = os.path.join(ROOT, "plugin.audio.audiobookshelf.sync", "resources")
    r = os.path.join(ROOT, "repository.mmbesar")
    addon_icon(os.path.join(a, "icon.png"))
    fanart(os.path.join(a, "fanart.jpg"))
    repo_icon(os.path.join(r, "icon.png"))
    fanart(os.path.join(r, "fanart.jpg"))
    print("art written")
