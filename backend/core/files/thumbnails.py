"""Image thumbnails: decode, shrink, encode as a small JPEG for `core_files.thumb`.

Memory safety lives in the order of operations: refuse oversized sources from the header before
any pixel is allocated, let the JPEG decoder downscale while decoding (`draft`), transpose only
when EXIF asks (it copies the image), shrink, and only then flatten alpha. One process-wide
semaphore bounds how many decodes run at once. Only the four web image decoders are allowed
near an upload; Pillow's other plugins (EPS via Ghostscript among them) never see one.
"""

from __future__ import annotations

import io
import logging
import threading
from pathlib import Path

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

THUMB_SIZE = 320  # longest edge; aspect ratio kept, the UI crops with object-fit
THUMB_MAX_BYTES = 28_000
JPEG_QUALITY_STEPS = (72, 58, 45)  # each a real drop, so the last try differs from the first
FORMATS = ("JPEG", "PNG", "GIF", "WEBP")

# Draft-capable (JPEG) sources decode at a fraction of full size, so they get a higher ceiling.
# Everything else decodes at full resolution: 8 MP is a ~32 MB RGBA buffer.
DRAFT_CAPABLE = ("JPEG", "MPO")
MAX_SOURCE_PIXELS, MAX_SOURCE_EDGE = 50_000_000, 12_000
MAX_UNDRAFTABLE_PIXELS, MAX_UNDRAFTABLE_EDGE = 8_000_000, 6_000
# Only frame 1 is thumbnailed; a long animation is left download-only rather than certified.
MAX_FRAMES = 8

# simplification: ~75 MB per in-flight decode at these ceilings, so two slots; the bound is per
# process (one worker). Re-do the arithmetic before raising either the slots or the upload cap.
decode_slots = threading.BoundedSemaphore(2)
DECODE_TIMEOUT_SECONDS = 5


def make(path: Path) -> bytes | None:
    """A JPEG thumbnail of the image at `path`, or None: not an image we decode, refused by a
    ceiling, no decode slot within the timeout, or the encode failed. Never raises."""
    try:
        im = Image.open(path, formats=FORMATS)  # parses the header only
    except Exception:
        return None
    with im:
        width, height = im.size
        draftable = im.format in DRAFT_CAPABLE
        max_pixels = MAX_SOURCE_PIXELS if draftable else MAX_UNDRAFTABLE_PIXELS
        max_edge = MAX_SOURCE_EDGE if draftable else MAX_UNDRAFTABLE_EDGE
        if not (0 < width * height <= max_pixels and max(width, height) <= max_edge):
            return None
        if getattr(im, "n_frames", 1) > MAX_FRAMES:
            return None
        if not decode_slots.acquire(timeout=DECODE_TIMEOUT_SECONDS):
            logger.warning("thumbnail skipped: no decode slot within %ss", DECODE_TIMEOUT_SECONDS)
            return None
        try:
            return _shrink(im)
        except Exception:
            logger.warning("thumbnail generation failed", exc_info=True)
            return None
        finally:
            decode_slots.release()


def _shrink(im: Image.Image) -> bytes | None:
    im.draft("RGB", (THUMB_SIZE * 2, THUMB_SIZE * 2))  # JPEG only; a no-op elsewhere
    try:
        orientation = im.getexif().get(0x0112)
    except Exception:  # a malformed EXIF block must not cost the thumbnail
        orientation = None
    if orientation not in (None, 1):
        im = ImageOps.exif_transpose(im)
    im.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)  # never upscales
    if im.mode not in ("RGB", "L"):
        rgba = im.convert("RGBA")
        im = Image.new("RGB", rgba.size, (255, 255, 255))
        im.paste(rgba, mask=rgba.getchannel("A"))
    im = im.convert("RGB")
    for quality in JPEG_QUALITY_STEPS:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)
        if buf.tell() <= THUMB_MAX_BYTES:
            return buf.getvalue()
    return None
