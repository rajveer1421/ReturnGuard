"""Image loading, background removal and capture-quality checks."""
import hashlib
import io
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps

from returnguard import config


def load_image(source) -> Image.Image:
    """Open a path, bytes or file-like object as an upright RGB image, downscaled."""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    img = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    img.thumbnail((config.MAX_IMAGE_SIDE, config.MAX_IMAGE_SIDE), Image.LANCZOS)
    return img


def image_digest(img: Image.Image) -> str:
    return hashlib.sha1(img.tobytes() + str(img.size).encode()).hexdigest()


@lru_cache(maxsize=1)
def _rembg_session():
    from rembg import new_session  # heavy import, load once
    return new_session(config.BG_MODEL)


def remove_background(img: Image.Image) -> Image.Image:
    """Return an RGBA cut-out of the main object, cropped to its bounding box.

    Results are cached on disk by image content, because evaluation re-processes
    the same photos many times."""
    cache = config.CACHE_DIR / "cutouts" / config.BG_MODEL / f"{image_digest(img)}.png"
    if cache.exists():
        return Image.open(cache).convert("RGBA")

    from rembg import remove
    cut = remove(img, session=_rembg_session()).convert("RGBA")
    alpha = np.array(cut.getchannel("A"))
    mask = alpha > 127
    if mask.any():
        ys, xs = np.where(mask)
        cut = cut.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))

    cache.parent.mkdir(parents=True, exist_ok=True)
    cut.save(cache)
    return cut


@dataclass
class CaptureQuality:
    object_fraction: float   # share of the original frame covered by the object
    sharpness: float         # Laplacian variance inside the object (grayscale)
    ok: bool
    problem: str | None


def _laplacian_var(gray: np.ndarray, mask: np.ndarray) -> float:
    lap = (np.roll(gray, -1, 0) + np.roll(gray, 1, 0) + np.roll(gray, -1, 1) + np.roll(gray, 1, 1) - 4 * gray)
    # erode the mask so the object outline (a hard edge against the background) doesn't count
    inner = mask & np.roll(mask, 3, 0) & np.roll(mask, -3, 0) & np.roll(mask, 3, 1) & np.roll(mask, -3, 1)
    return float(lap[inner].var()) if inner.sum() > 100 else 0.0


def assess_quality(original: Image.Image, cutout: Image.Image) -> CaptureQuality:
    """Is this photo usable as evidence? Measures focus on the object itself,
    not the silhouette edge, and checks the object is actually in frame."""
    alpha = np.array(cutout.getchannel("A")) > 127
    fraction = alpha.sum() / (original.width * original.height)
    gray = np.array(cutout.convert("L"), dtype=np.float32)
    sharp = _laplacian_var(gray, alpha)

    problem = None
    if fraction < config.MIN_OBJECT_FRACTION:
        problem = "Product not found in the photo (or far too small). Retake closer."
    elif sharp < config.MIN_SHARPNESS:
        problem = "Photo is too blurry to use as evidence. Retake with the camera steady."
    return CaptureQuality(round(float(fraction), 4), round(sharp, 1), problem is None, problem)
