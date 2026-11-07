"""
Draws MXB's icon (a listening ring with three voice bars) and saves a multi-size .ico.

    python packaging/make_icon.py packaging/mxb.ico

Generated at build time so no binary sits in git. Needs Pillow (already in requirements.txt).
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

BG = (18, 21, 30, 255)        # #12151E, the tray menu background
ACCENT = (0, 229, 255, 255)   # #00E5FF, the tray menu accent
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw(size: int = 256) -> Image.Image:
    scale = 4  # draw big, downsample: smooth edges at every size
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = s * 0.04
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=s * 0.22, fill=BG)
    ring = s * 0.16
    d.ellipse([ring, ring, s - ring, s - ring], outline=ACCENT, width=max(2, int(s * 0.055)))
    bar_w = s * 0.075
    heights = [0.20, 0.36, 0.20]
    gap = s * 0.055
    total = 3 * bar_w + 2 * gap
    x = (s - total) / 2
    for h in heights:
        bh = s * h
        y0 = (s - bh) / 2
        d.rounded_rectangle([x, y0, x + bar_w, y0 + bh], radius=bar_w / 2, fill=ACCENT)
        x += bar_w + gap
    return img.resize((size, size), Image.LANCZOS)


def main(out: str) -> Path:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    draw(256).save(path, format="ICO", sizes=[(n, n) for n in SIZES])
    return path


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "packaging/mxb.ico"))
