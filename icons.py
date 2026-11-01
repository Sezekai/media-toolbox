"""Line icons drawn with Pillow, so no image files need to be bundled with the app."""
from PIL import Image, ImageDraw
from PySide6.QtGui import QIcon, QImage, QPixmap

import theme

SUPERSAMPLE = 4  # draw bigger, then shrink, for smooth edges


def _draw(name, colour, px):
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = px / 24            # the icons are designed on a 24 x 24 grid
    w = max(1, round(2.2 * k))

    def pts(p):
        return [(x * k, y * k) for x, y in p]

    def line(p):
        d.line(pts(p), fill=colour, width=w, joint="curve")

    def box(x0, y0, x1, y1, r=0):
        d.rounded_rectangle([x0 * k, y0 * k, x1 * k, y1 * k], radius=r * k, outline=colour, width=w)

    def solid(p):
        d.polygon(pts(p), fill=colour)

    def dot(x, y, r):
        d.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=colour)

    def folder():
        line([(3, 7), (9.5, 7), (11.5, 9), (21, 9), (21, 19), (3, 19), (3, 7)])

    if name == "silent":
        line([(3, 9), (7, 9), (12, 5), (12, 19), (7, 15), (3, 15), (3, 9)])
        line([(16, 9), (21, 15)])
        line([(21, 9), (16, 15)])
    elif name == "gif":
        box(3, 5, 21, 19, 3)
        solid([(10, 9), (10, 15), (15.5, 12)])
    elif name == "zip":
        folder()
        d.rectangle([11 * k, 11 * k, 13 * k, 13 * k], fill=colour)
        d.rectangle([11 * k, 14 * k, 13 * k, 16 * k], fill=colour)
    elif name == "image":
        box(3, 4, 21, 20, 3)
        line([(5, 17), (10, 11.5), (13.5, 15.5), (16, 13), (19, 17)])
        dot(8.5, 8.5, 1.6)
    elif name == "duplicate":
        box(3, 7, 15, 19, 2)
        box(9, 3, 21, 15, 2)
    elif name == "copy_folder":
        folder()
        line([(12, 11), (12, 16)])
        line([(9.5, 13.5), (14.5, 13.5)])
    elif name == "search":
        d.ellipse([(10.5 - 6) * k, (10.5 - 6) * k, (10.5 + 6) * k, (10.5 + 6) * k], outline=colour, width=w)
        line([(15, 15), (20, 20)])
    elif name == "move":
        line([(3, 12), (16, 12)])
        line([(12, 8), (16, 12), (12, 16)])
        line([(4, 19.5), (20, 19.5)])
    elif name == "folder":
        folder()
    elif name == "brush":
        line([(4, 20), (9, 15)])
        solid([(9, 13), (14, 8), (17, 11), (12, 16)])
        line([(15, 7), (18, 4)])
    elif name == "logo":
        box(3, 3, 11, 11, 2)
        box(13, 3, 21, 11, 2)
        box(8, 13, 16, 21, 2)
    return img


_cache = {}


def icon(name, colour=None, size=20):
    """A QIcon of the named icon, drawn at the given size in pixels."""
    colour = colour or theme.TEXT
    key = (name, colour, size)
    if key not in _cache:
        img = _draw(name, colour, size * SUPERSAMPLE).resize((size, size), Image.LANCZOS).convert("RGBA")
        qimg = QImage(img.tobytes("raw", "RGBA"), size, size, 4 * size, QImage.Format_RGBA8888).copy()
        _cache[key] = QIcon(QPixmap.fromImage(qimg))
    return _cache[key]
