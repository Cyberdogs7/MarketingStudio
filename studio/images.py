"""Image normalization helpers.

Uploaded files are often WebP/JPEG saved under a .png name (e.g. from a browser
file picker). ComfyUI's LoadImage and other strict PNG consumers fail on those,
so we re-encode to a real PNG in place.
"""
from __future__ import annotations

from pathlib import Path


def ensure_png(path: Path | str) -> bool:
    """Re-encode ``path`` to a real PNG in place if it isn't already. Returns True if converted."""
    try:
        from PIL import Image
        with Image.open(str(path)) as im:
            fmt = im.format
            im.load()
        if fmt == "PNG":
            return False
        with Image.open(str(path)) as im:
            im.save(str(path), format="PNG")
        return True
    except Exception:
        return False
