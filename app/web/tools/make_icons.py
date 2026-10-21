"""Draws the app icons (a house with a door, flat) into web/public. Run once after changing the design:

    python tools/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

BG = (60, 52, 137)  # purple 800
FG = (238, 237, 254)  # purple 50
OUT = Path(__file__).resolve().parent.parent / "public"


def icon(size: int, maskable: bool) -> Image.Image:
    s = size * 4  # draw large, scale down for smooth edges
    img = Image.new("RGBA", (s, s), BG + (255,))
    if not maskable:
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 5, fill=BG + (255,))
    d = ImageDraw.Draw(img)
    pad = s * (0.24 if maskable else 0.18)
    left, right, top, bottom = pad, s - pad, pad, s - pad
    mid = s / 2
    roof = top + (bottom - top) * 0.42
    w = s * 0.055
    d.line([(left, roof), (mid, top), (right, roof)], fill=FG, width=int(w), joint="curve")
    d.line([(left + w * 0.6, roof - w * 0.3), (left + w * 0.6, bottom), (right - w * 0.6, bottom),
            (right - w * 0.6, roof - w * 0.3)], fill=FG, width=int(w), joint="curve")
    door_w, door_h = (right - left) * 0.24, (bottom - roof) * 0.55
    d.rounded_rectangle((mid - door_w / 2, bottom - door_h, mid + door_w / 2, bottom), radius=int(door_w / 2.5), fill=FG)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192, False).save(OUT / "icon-192.png")
    icon(512, False).save(OUT / "icon-512.png")
    icon(512, True).save(OUT / "icon-maskable-512.png")
    icon(180, True).convert("RGB").save(OUT / "apple-touch-icon.png")
    print("icons written to", OUT)
