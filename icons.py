"""Line icons drawn with Pillow, so no image files need to be bundled with the app.

One set on a 24-unit grid: 1.6 stroke, round ends, outlines only (DESIGN.md, "Icons").
16 px in controls, 19 px in the rail."""
import math

from PIL import Image, ImageDraw
from PySide6.QtGui import QIcon, QImage, QPixmap

import theme

SUPERSAMPLE = 4  # draw bigger, then shrink, for smooth edges
STROKE = 1.6     # on the 24-unit grid


def _draw(name, colour, size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = size / 24
    w = max(1, round(STROKE * k))

    def line(*points):
        pts = [(x * k, y * k) for x, y in points]
        d.line(pts, fill=colour, width=w, joint="curve")
        r = w / 2
        for x, y in (pts[0], pts[-1]):  # round ends
            d.ellipse([x - r, y - r, x + r, y + r], fill=colour)

    def box(x0, y0, x1, y1, r=2.5):
        d.rounded_rectangle([x0 * k, y0 * k, x1 * k, y1 * k], radius=r * k, outline=colour, width=w)

    def ring(cx, cy, r):
        d.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], outline=colour, width=w)

    def dot(cx, cy, r=1.1):
        d.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], fill=colour)

    def folder():
        line((3.5, 18.5), (3.5, 6.5), (9, 6.5), (11, 8.5), (20.5, 8.5), (20.5, 18.5), (3.5, 18.5))

    if name == "silent":         # speaker with a cross
        line((4, 9.5), (7.5, 9.5), (12, 5.5), (12, 18.5), (7.5, 14.5), (4, 14.5), (4, 9.5))
        line((15.5, 9.5), (20, 14.5))
        line((20, 9.5), (15.5, 14.5))
    elif name == "gif":          # frame with a play mark
        box(3.5, 5.5, 20.5, 18.5)
        line((10.5, 9.5), (10.5, 14.5), (14.5, 12), (10.5, 9.5))
    elif name == "duplicate":    # two overlapping frames
        box(3.5, 8.5, 15.5, 20.5)
        line((8.5, 5.5), (8.5, 5), (9, 3.5), (19, 3.5), (20.5, 5), (20.5, 14), (19, 15.5), (18.5, 15.5))
    elif name == "zip":          # folder with a zip line
        folder()
        line((12, 10.5), (12, 11.5))
        line((12, 13.5), (12, 14.5))
        line((12, 16.5), (12, 17))
    elif name == "image":        # picture
        box(3.5, 4.5, 20.5, 19.5)
        line((6.5, 16.5), (10.5, 12), (13.5, 15), (15.5, 13), (18, 16.5))
        ring(9, 8.8, 1.4)
    elif name == "copy_folder":  # folder tree
        line((5, 4.5), (5, 17.5), (10, 17.5))
        line((5, 10.5), (10, 10.5))
        box(10, 7.5, 20.5, 13.5, 1.8)
        box(10, 14.5, 20.5, 20.5, 1.8)
    elif name == "search":
        ring(10.5, 10.5, 6)
        line((15, 15), (20, 20))
    elif name == "move":
        line((4, 12), (17, 12))
        line((13, 8), (17, 12), (13, 16))
        line((20.5, 5), (20.5, 19))
    elif name == "log":          # lines of text
        line((5, 7), (19, 7))
        line((5, 12), (19, 12))
        line((5, 17), (14, 17))
    elif name == "look":         # palette
        line((12, 3.5), (8, 4.5), (4.8, 7.5), (3.5, 12), (4.8, 16.5), (8, 19.5), (12, 20.5), (13.4, 19.6),
             (13.4, 17.8), (12.6, 16.2), (13.2, 14.6), (15, 14.2), (17.5, 14.2), (19.6, 13), (20.5, 11),
             (19.6, 7.5), (16.5, 4.6), (12, 3.5))
        dot(8, 12)
        dot(9.8, 8)
        dot(14.2, 8)
    elif name == "settings":     # gear
        ring(12, 12, 3)
        for i in range(8):
            a = math.radians(i * 45)
            line((12 + 5.6 * math.cos(a), 12 + 5.6 * math.sin(a)), (12 + 8.4 * math.cos(a), 12 + 8.4 * math.sin(a)))
        ring(12, 12, 5.6)
    elif name == "keys":         # keyboard
        box(3, 6.5, 21, 17.5, 1.8)
        for x in (7, 10.3, 13.6, 17):
            dot(x, 10)
        line((8, 14), (16, 14))
    elif name == "stop":
        box(7, 7, 17, 17, 1.5)
    elif name == "pause":
        line((9, 6.5), (9, 17.5))
        line((15, 6.5), (15, 17.5))
    elif name == "play":
        line((8, 5.5), (8, 18.5), (18.5, 12), (8, 5.5))
    elif name == "folder":
        folder()
    elif name == "folder_plus":
        folder()
        line((12, 11), (12, 16))
        line((9.5, 13.5), (14.5, 13.5))
    elif name == "warn":
        line((12, 4), (21, 19.5), (3, 19.5), (12, 4))
        line((12, 10), (12, 14))
        dot(12, 16.8, 0.9)
    elif name == "check":
        line((5, 12.5), (9.5, 17), (19, 7.5))
    elif name == "error":        # circle with a cross
        ring(12, 12, 8.5)
        line((9, 9), (15, 15))
        line((15, 9), (9, 15))
    elif name == "info":
        ring(12, 12, 8.5)
        line((12, 11), (12, 16))
        dot(12, 8, 0.9)
    elif name == "x":
        line((6.5, 6.5), (17.5, 17.5))
        line((17.5, 6.5), (6.5, 17.5))
    elif name == "list":
        for y in (7, 12, 17):
            dot(5, y)
            line((9, y), (19.5, y))
    elif name == "grid":
        box(4, 4, 11, 11, 1.5)
        box(13, 4, 20, 11, 1.5)
        box(4, 13, 11, 20, 1.5)
        box(13, 13, 20, 20, 1.5)
    elif name == "gallery":
        box(3.5, 4.5, 15, 19.5, 1.8)
        line((18, 6), (18, 18))
        line((20.8, 8), (20.8, 16))
    elif name == "undo":
        line((8, 5), (4, 9), (8, 13))
        line((4, 9), (14, 9), (17.5, 10.5), (19.5, 14), (17.5, 17.5), (14, 19), (10, 19))
    elif name == "sort_up":
        line((7, 16), (12, 8), (17, 16))
    elif name == "sort_down":
        line((7, 8), (12, 16), (17, 8))
    elif name == "gpu":
        box(3.5, 6.5, 20.5, 17.5, 1.8)
        ring(10, 12, 2.6)
        line((15, 10), (17.5, 10))
        line((15, 14), (17.5, 14))
    elif name == "wrench":
        line((14.5, 4.5), (11.5, 7.5), (11.5, 10.5), (4.5, 17.5), (6.5, 19.5), (13.5, 12.5), (16.5, 12.5), (19.5, 9.5))
    elif name == "copy":
        box(8.5, 8.5, 20, 20, 2)
        line((15.5, 5.5), (15.5, 5), (14.5, 4), (5, 4), (4, 5), (4, 14.5), (5, 15.5), (5.5, 15.5))
    elif name == "win_min":
        line((7, 12), (17, 12))
    elif name == "win_max":
        box(7, 7, 17, 17, 0.6)
    elif name == "win_restore":
        box(7, 9, 15, 17, 0.6)
        line((9, 7), (17, 7), (17, 15))
    elif name == "win_close":
        line((7, 7), (17, 17))
        line((17, 7), (7, 17))
    elif name == "logo":         # three tiles
        box(3.5, 3.5, 10.5, 10.5, 2)
        box(13.5, 3.5, 20.5, 10.5, 2)
        box(8.5, 13.5, 15.5, 20.5, 2)
    return img


_cache = {}


def _to_icon(img, size):
    qimg = QImage(img.tobytes("raw", "RGBA"), size, size, 4 * size, QImage.Format_RGBA8888).copy()
    return QIcon(QPixmap.fromImage(qimg))


def icon(name, colour=None, size=16):
    """A QIcon of the named icon, drawn at the given size in pixels."""
    colour = colour or theme.TEXT
    key = (name, colour, size)
    if key not in _cache:
        img = _draw(name, colour, size * SUPERSAMPLE).resize((size, size), Image.LANCZOS).convert("RGBA")
        _cache[key] = _to_icon(img, size)
    return _cache[key]


def pixmap(name, colour=None, size=16):
    return icon(name, colour, size).pixmap(size, size)


def swatch(colours, size=18, round_=True):
    """A colour sample: one colour, or a gradient of several (for theme and accent pickers)."""
    if isinstance(colours, str):
        colours = [colours]
    big = size * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    strip = Image.new("RGBA", (big, big))
    px = strip.load()
    stops = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in colours]
    for x in range(big):
        t = x / max(1, big - 1) * (len(stops) - 1)
        i = min(int(t), len(stops) - 2) if len(stops) > 1 else 0
        f = t - i
        a, b = stops[i], stops[min(i + 1, len(stops) - 1)]
        c = tuple(round(a[j] + (b[j] - a[j]) * f) for j in range(3)) + (255,)
        for y in range(big):
            px[x, y] = c
    mask = Image.new("L", (big, big), 0)
    inset = big * 0.08
    if round_:
        ImageDraw.Draw(mask).ellipse([inset, inset, big - inset, big - inset], fill=255)
    else:
        ImageDraw.Draw(mask).rounded_rectangle([inset, inset, big - inset, big - inset], radius=big * 0.18, fill=255)
    img.paste(strip, (0, 0), mask)
    img = img.resize((size, size), Image.LANCZOS).convert("RGBA")
    return _to_icon(img, size)
