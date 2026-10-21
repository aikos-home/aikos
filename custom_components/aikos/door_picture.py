"""The door picture (A12/A41): any photo → the grey PNG the door's welcome page shows (contract
`text.aikos_intercom_screen_photo_url`: at most 492×536, the panel's 16 grey levels). Same steps as the door's test
script: turned upright, fitted, grey, contrast stretched, dithered. No Home Assistant code.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps

W, H = 492, 536
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 50_000_000        # a decompression bomb is refused, not decoded


class PictureError(ValueError):
    pass


def panel_png(data: bytes) -> bytes:
    if not data or len(data) > MAX_BYTES:
        raise PictureError("no picture or too large")
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_PIXELS:
            raise PictureError("too many pixels")
        img = ImageOps.exif_transpose(img).convert("L")
    except (OSError, Image.DecompressionBombError, SyntaxError) as e:
        raise PictureError(f"not a picture: {e}") from None
    img = ImageOps.contain(img, (W, H), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)
    levels = Image.new("P", (1, 1))
    levels.putpalette([v for g in range(16) for v in (g * 17,) * 3] + [0] * (256 - 16) * 3)
    grey = img.convert("RGB").quantize(palette=levels, dither=Image.FLOYDSTEINBERG).convert("L")
    out = io.BytesIO()
    grey.save(out, format="PNG", optimize=True)
    return out.getvalue()
