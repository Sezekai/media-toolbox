"""Line icons drawn with Pillow, so no image files need to be bundled with the app.

All icons sit on a 24 x 24 grid, use the same stroke weight and round ends, and are outlines only."""
from PIL import Image, ImageDraw
from PySide6.QtGui import QIcon, QImage, QPixmap

import theme

SUPERSAMPLE = 4  # draw bigger, then shrink, for smooth edges
STROKE = 1.7     # on the 24-unit grid


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

    def folder():
        line((3.5, 18.5), (3.5, 6.5), (9, 6.5), (11, 8.5), (20.5, 8.5), (20.5, 18.5), (3.5, 18.5))

    if name == "silent":       # speaker with a cross
        line((4, 9.5), (7.5, 9.5), (12, 5.5), (12, 18.5), (7.5, 14.5), (4, 14.5), (4, 9.5))
        line((15.5, 9.5), (20, 14.5))
        line((20, 9.5), (15.5, 14.5))
    elif name == "gif":        # frame with a play mark
        box(3.5, 5.5, 20.5, 18.5)
        line((10.5, 9.5), (10.5, 14.5), (14.5, 12), (10.5, 9.5))
    elif name == "duplicate":  # two overlapping frames
        box(3.5, 8.5, 15.5, 20.5)
        line((8.5, 5.5), (8.5, 5), (9, 3.5), (19, 3.5), (20.5, 5), (20.5, 14), (19, 15.5), (18.5, 15.5))
    elif name == "zip":        # folder with a zip line
        folder()
        line((12, 10.5), (12, 11.5))
        line((12, 13.5), (12, 14.5))
        line((12, 16.5), (12, 17))
    elif name == "image":      # picture
        box(3.5, 4.5, 20.5, 19.5)
        line((6.5, 16.5), (10.5, 12), (13.5, 15), (15.5, 13), (18, 16.5))
        ring(9, 8.8, 1.4)
    elif name == "copy_folder":  # folder with a plus
        folder()
        line((12, 11), (12, 16))
        line((9.5, 13.5), (14.5, 13.5))
    elif name == "search":
        ring(10.5, 10.5, 6)
        line((15, 15), (20, 20))
    elif name == "move":
        line((4, 12), (17, 12))
        line((13, 8), (17, 12), (13, 16))
        line((20.5, 5), (20.5, 19))
    elif name == "log":        # lines of text
        line((5, 7), (19, 7))
        line((5, 12), (19, 12))
        line((5, 17), (14, 17))
    elif name == "logo":       # three tiles
        box(3.5, 3.5, 10.5, 10.5, 2)
        box(13.5, 3.5, 20.5, 10.5, 2)
        box(8.5, 13.5, 15.5, 20.5, 2)
    return img


_cache = {}


def icon(name, colour=None, size=18):
    """A QIcon of the named icon, drawn at the given size in pixels."""
    colour = colour or theme.TEXT
    key = (name, colour, size)
    if key not in _cache:
        img = _draw(name, colour, size * SUPERSAMPLE).resize((size, size), Image.LANCZOS).convert("RGBA")
        qimg = QImage(img.tobytes("raw", "RGBA"), size, size, 4 * size, QImage.Format_RGBA8888).copy()
        _cache[key] = QIcon(QPixmap.fromImage(qimg))
    return _cache[key]
