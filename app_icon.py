"""The app's icon: a rounded square in Sunset (amber, pink, violet), with the Media Toolbox mark (a gear with
a play button in it) in near-black. Like the suite's other apps, the square fills the whole icon, so it's as big as other apps' icons
in the taskbar and File Explorer.

`python app_icon.py MediaToolbox.ico` writes the .ico the build puts into the .exe."""
import sys

from PIL import Image, ImageDraw

import math

STOPS = [(0xff, 0xb3, 0x47), (0xff, 0x6a, 0x88), (0xb4, 0x7c, 0xff)]  # Sunset: amber, pink, violet
INK = (0x0b, 0x0c, 0x0f)
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def mark(draw, u, colour, cut):
    """The Media Toolbox mark on a 24-unit grid: a gear (tools) with a play button (media) in its middle."""
    cx = cy = 12.0
    pts = []
    teeth, outer, inner = 8, 9.6, 9.6 * 0.78
    for i in range(teeth * 4):
        a = i / (teeth * 4) * 2 * math.pi + 0.2
        r = outer if i % 4 in (0, 1) else inner
        pts.append(((cx + r * math.cos(a)) * u, (cy + r * math.sin(a)) * u))
    draw.polygon(pts, fill=colour)
    hole = 5.4
    draw.ellipse([(cx - hole) * u, (cy - hole) * u, (cx + hole) * u, (cy + hole) * u], fill=cut)
    h, px = 6.6, cx + 0.5
    draw.polygon([((px - h * 0.42) * u, (cy - h / 2) * u), ((px - h * 0.42) * u, (cy + h / 2) * u),
                  ((px + h * 0.5) * u, cy * u)], fill=colour)


def image(size):
    """The icon at size × size pixels (drawn 4× larger, then scaled down, for smooth edges)."""
    big = size * 4
    margin = round(big * (0.0 if size <= 24 else 0.03))  # tiny sizes use every pixel
    strip = Image.new("RGB", (big, 1))
    px = strip.load()
    for x in range(big):
        t = x / (big - 1) * (len(STOPS) - 1)
        i = min(int(t), len(STOPS) - 2)
        f = t - i
        px[x, 0] = tuple(round(a + (b - a) * f) for a, b in zip(STOPS[i], STOPS[i + 1]))
    fill = strip.resize((big, big))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, big - 1 - margin, big - 1 - margin], big * 0.22,
                                           fill=255)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    img.paste(fill, (0, 0), mask)
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    mark(ImageDraw.Draw(layer), big / 24, INK + (255,), (0, 0, 0, 0))
    img.alpha_composite(layer)
    return img.resize((size, size), Image.LANCZOS)


def write_ico(path):
    imgs = [image(s) for s in SIZES]
    imgs[-1].save(path, format="ICO", sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])


def qicon():
    """The icon for the window and taskbar."""
    from PySide6.QtGui import QIcon, QImage, QPixmap
    icon = QIcon()
    for s in SIZES:
        img = image(s)
        q = QImage(img.tobytes("raw", "RGBA"), s, s, 4 * s, QImage.Format_RGBA8888).copy()
        icon.addPixmap(QPixmap.fromImage(q))
    return icon


if __name__ == "__main__":
    write_ico(sys.argv[1] if len(sys.argv) > 1 else "MediaToolbox.ico")
