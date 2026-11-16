"""The app's icon: a rounded square in the suite's Lime → Teal, with the Media Toolbox mark (three tiles) in
near-black. Like the suite's other apps, the square fills the whole icon, so it's as big as other apps' icons
in the taskbar and File Explorer.

`python app_icon.py MediaToolbox.ico` writes the .ico the build puts into the .exe."""
import sys

from PIL import Image, ImageDraw

LIME, TEAL, INK = (0xb6, 0xf0, 0x5a), (0x2f, 0xd6, 0xb4), (0x0b, 0x0c, 0x0f)
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def image(size):
    """The icon at size × size pixels (drawn 4× larger, then scaled down, for smooth edges)."""
    big = size * 4
    margin = round(big * (0.0 if size <= 24 else 0.03))  # tiny sizes use every pixel
    radius = big * 0.22
    strip = Image.new("RGB", (big, 1))
    px = strip.load()
    for x in range(big):
        t = x / (big - 1)
        px[x, 0] = tuple(round(a + (b - a) * t) for a, b in zip(LIME, TEAL))
    fill = strip.resize((big, big))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, big - 1 - margin, big - 1 - margin], radius, fill=255)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    img.paste(fill, (0, 0), mask)
    # the mark: three solid tiles, two above and one below, centred
    d = ImageDraw.Draw(img)
    unit = big / 24
    thick = size <= 24  # small icons get bigger tiles so they stay readable
    tiles = ([(4, 4, 11.2, 11.2), (12.8, 4, 20, 11.2), (8.4, 12.8, 15.6, 20)] if thick else
             [(5.5, 5.5, 11.3, 11.3), (12.7, 5.5, 18.5, 11.3), (9.1, 12.7, 14.9, 18.5)])
    for x0, y0, x1, y1 in tiles:
        d.rounded_rectangle([x0 * unit, y0 * unit, x1 * unit, y1 * unit], radius=unit * 1.4, fill=INK + (255,))
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
