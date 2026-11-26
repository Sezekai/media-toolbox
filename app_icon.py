"""The app's icon: the Media Toolbox mark (a gear with a play button in it) on its own, filled with the Sunset
gradient (amber, pink, violet), with a soft shadow. Like the suite's other apps, the square fills the whole icon, so it's as big as other apps' icons
in the taskbar and File Explorer.

`python app_icon.py MediaToolbox.ico` writes the .ico the build puts into the .exe."""
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

import math

STOPS = [(0xff, 0xb3, 0x47), (0xff, 0x6a, 0x88), (0xb4, 0x7c, 0xff)]  # Sunset: amber, pink, violet
ANGLE = 146  # the same direction as the Sunset theme's accent
INK = (0xff, 0xff, 0xff)  # the gear and play are white on the gradient
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def _rounded_triangle(draw, u, pts, radius, fill):
    """A triangle with its corners rounded to radius (all in grid units)."""
    a, b, c = (math.dist(pts[1], pts[2]), math.dist(pts[0], pts[2]), math.dist(pts[0], pts[1]))
    ix = (a * pts[0][0] + b * pts[1][0] + c * pts[2][0]) / (a + b + c)
    iy = (a * pts[0][1] + b * pts[1][1] + c * pts[2][1]) / (a + b + c)
    area = abs((pts[1][0] - pts[0][0]) * (pts[2][1] - pts[0][1]) - (pts[2][0] - pts[0][0]) * (pts[1][1] - pts[0][1])) / 2
    rin = area / ((a + b + c) / 2)
    r = min(radius, rin * 0.95)
    k = (rin - r) / rin  # shrink towards the centre, then grow back by r with round ends
    q = [((ix + (x - ix) * k) * u, (iy + (y - iy) * k) * u) for x, y in pts]
    draw.polygon(q, fill=fill)
    rr = r * u
    for i in range(3):
        (x0, y0), (x1, y1) = q[i], q[(i + 1) % 3]
        draw.line([(x0, y0), (x1, y1)], fill=fill, width=max(1, int(2 * rr)))
        draw.ellipse([x0 - rr, y0 - rr, x0 + rr, y0 + rr], fill=fill)


def mark_mask(big):
    """The Media Toolbox mark as a big × big mask on a 24-unit grid: a gear with softly rounded teeth (tools)
    and a rounded play button (media) in its middle."""
    u = big / 24
    cx = cy = 12.0
    m = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(m)
    pts = []
    teeth, outer, inner = 8, 9.6, 9.6 * 0.76
    for i in range(teeth * 4):
        a = i / (teeth * 4) * 2 * math.pi + 0.2
        r = outer if i % 4 in (0, 1) else inner
        pts.append(((cx + r * math.cos(a)) * u, (cy + r * math.sin(a)) * u))
    d.polygon(pts, fill=255)
    # soften the teeth: blur, then cut back to a clean edge
    m = m.filter(ImageFilter.GaussianBlur(0.9 * u)).point(lambda v: 255 if v > 127 else 0)
    d = ImageDraw.Draw(m)
    hole = 5.4
    d.ellipse([(cx - hole) * u, (cy - hole) * u, (cx + hole) * u, (cy + hole) * u], fill=0)
    h, px = 6.6, cx + 0.5
    _rounded_triangle(d, u, [(px - h * 0.42, cy - h / 2), (px - h * 0.42, cy + h / 2), (px + h * 0.5, cy)], 0.85, 255)
    return m


def mark_layer(big, colour=INK, shadow=True):
    """The mark in a colour, with a soft shadow under it, as a big × big RGBA image."""
    u = big / 24
    m = mark_mask(big)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    if shadow:
        sh = ImageChops.offset(m, 0, max(1, int(0.5 * u))).filter(ImageFilter.GaussianBlur(0.8 * u))
        out.putalpha(sh.point(lambda v: int(v * 0.55)))
    if isinstance(colour, str):
        colour = tuple(int(colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    ink = Image.new("RGBA", (big, big), tuple(colour[:3]) + (0,))
    ink.putalpha(m)
    out.alpha_composite(ink)
    return out


def _gradient(big, stops, angle):
    """A big × big RGB image of the colours along a CSS-style angle (degrees, 90 = left to right)."""
    a = math.radians(angle)
    sx, sy = math.sin(a), -math.cos(a)
    n = len(stops) - 1
    # the colour at each position along the gradient line, as a lookup
    line = []
    for k in range(256):
        t = k / 255 * n
        i = min(int(t), n - 1)
        f = t - i
        line.append(tuple(round(c0 + (c1 - c0) * f) for c0, c1 in zip(stops[i], stops[i + 1])))
    small = 64
    img = Image.new("RGB", (small, small))
    px = img.load()
    half = (abs(sx) + abs(sy)) / 2
    for y in range(small):
        for x in range(small):
            u, v = (x + 0.5) / small - 0.5, (y + 0.5) / small - 0.5
            t = min(1.0, max(0.0, (u * sx + v * sy) / (2 * half) + 0.5))
            px[x, y] = line[round(t * 255)]
    return img.resize((big, big), Image.BILINEAR)


def logo_image(size, stops=None, angle=ANGLE):
    """The logo on its own: the mark filled with the gradient, with a soft shadow, filling the whole size.
    Used for the app's icon (Explorer, taskbar, window) and, in the theme's accent, at the top of the rail."""
    stops = [tuple(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) if isinstance(c, str) else c
             for c in (stops or STOPS)]
    if len(stops) == 1:
        stops = stops * 2
    big = size * 4
    grow = 1.16  # the gear fills the square, leaving a little room for its shadow
    m_big = int(big * grow)
    mark = mark_mask(m_big)
    off = (big - m_big) // 2
    m = Image.new("L", (big, big), 0)
    m.paste(mark, (off, off - int(big / 24 * 0.3)))
    u = big / 24
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    strength = 0.38 if size <= 24 else 0.5
    sh = ImageChops.offset(m, 0, max(1, int(0.45 * u))).filter(ImageFilter.GaussianBlur(0.7 * u))
    out.putalpha(sh.point(lambda v: int(v * strength)))
    fill = _gradient(big, stops, angle).convert("RGBA")
    fill.putalpha(m)
    out.alpha_composite(fill)
    return out.resize((size, size), Image.LANCZOS)


def image(size):
    """The app's icon at size × size pixels."""
    return logo_image(size)


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
