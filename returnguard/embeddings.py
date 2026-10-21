"""Local visual features: object-only DINOv2 embeddings and a colour signature.

Why object-only pooling: the cut-out is padded to a square before the ViT sees
it. For tall items (bottles, shakers) 65-77% of the patches are padding, and a
plain patch-mean then scores *any* two tall objects as similar because they
share the padding. We average only the patches the background-removal mask
marks as object.

Why a colour signature: DINOv2 is trained with colour-jitter augmentation, so it
is deliberately colour-invariant. A blue speaker and a black speaker of the same
model look almost identical to it. The median chroma of the object pixels
catches exactly that substitution, for free.
"""
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import torch
from PIL import Image

from returnguard import config

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_PAD = tuple(int(v * 255) for v in _MEAN)   # pad with the normalisation mean -> ~zero input


@lru_cache(maxsize=1)
def _model():
    from transformers import AutoModel
    model = AutoModel.from_pretrained(config.EMBED_MODEL)
    model.eval()
    return model


def _square(img: Image.Image, fill) -> Image.Image:
    side = max(img.size)
    canvas = Image.new(img.mode, (side, side), fill)
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


@dataclass
class ViewFeatures:
    embedding: np.ndarray      # L2-normalised object-only patch mean, float32 [D]
    lab: np.ndarray            # median object colour (L*, a*, b*), float32 [3]
    object_patches: int

    def to_dict(self):
        return {"embedding": self.embedding.tolist(), "lab": self.lab.tolist(),
                "object_patches": self.object_patches}

    @classmethod
    def from_dict(cls, d):
        return cls(np.asarray(d["embedding"], dtype=np.float32), np.asarray(d["lab"], dtype=np.float32),
                   int(d["object_patches"]))


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB [0,255] -> CIE Lab (D65)."""
    c = rgb.astype(np.float32) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = 116 * f[:, 1] - 16
    a = 500 * (f[:, 0] - f[:, 1])
    b = 200 * (f[:, 1] - f[:, 2])
    return np.stack([L, a, b], axis=1)


def color_signature(cutout: Image.Image) -> np.ndarray:
    """Median CIE Lab colour of the object pixels (L*, a*, b*).

    A median over thousands of object pixels is robust to highlights, shadows
    and small background-removal errors. A histogram was tried first and was too
    sensitive to white-balance shifts between two photos of the same item."""
    arr = np.array(cutout.convert("RGBA"))
    pix = arr[arr[..., 3] > 127][:, :3]
    if len(pix) < 50:
        return np.full(3, np.nan, dtype=np.float32)
    if len(pix) > 40000:
        pix = pix[np.random.default_rng(0).choice(len(pix), 40000, replace=False)]
    return np.median(_rgb_to_lab(pix), axis=0).astype(np.float32)


@torch.inference_mode()
def view_features(cutout: Image.Image) -> ViewFeatures:
    size = config.EMBED_SIZE
    rgba = cutout.convert("RGBA")
    rgb = _square(rgba.convert("RGB"), _PAD).resize((size, size), Image.BICUBIC)
    # put the original pixels back only where the object is; background -> pad colour
    alpha_sq = _square(rgba.getchannel("A"), 0).resize((size, size), Image.BILINEAR)
    a = np.array(alpha_sq, dtype=np.float32)[..., None] / 255.0
    pixels = np.array(rgb, dtype=np.float32) * a + np.array(_PAD, dtype=np.float32) * (1 - a)

    x = (pixels / 255.0 - _MEAN) / _STD
    x = torch.from_numpy(x.transpose(2, 0, 1)).unsqueeze(0)
    tokens = _model()(pixel_values=x).last_hidden_state[0]          # [1 + N (+ registers), D]
    grid = size // 14
    patches = tokens[-grid * grid:]                                   # patch tokens are the last N

    patch_alpha = np.array(alpha_sq.resize((grid, grid), Image.BOX), dtype=np.float32).flatten() / 255.0
    weights = torch.from_numpy((patch_alpha > 0.5).astype(np.float32))
    if weights.sum() < 1:
        weights = torch.ones_like(weights)
    emb = (patches * weights[:, None]).sum(0) / weights.sum()
    emb = torch.nn.functional.normalize(emb, dim=0)
    return ViewFeatures(emb.numpy().astype(np.float32), color_signature(cutout), int(weights.sum()))


def shape_similarity(a: ViewFeatures, b: ViewFeatures) -> float:
    return float(np.dot(a.embedding, b.embedding))


def color_shift(a: ViewFeatures, b: ViewFeatures) -> float:
    """Chroma difference (Delta E in the a*b* plane) between the two objects' median
    colours. Lightness is left out because exposure changes it between photos.
    Re-photographing the same item stays below ~2.6 on our data; the blue vs black
    speaker of the same model is ~4."""
    if np.isnan(a.lab).any() or np.isnan(b.lab).any():
        return 0.0
    return float(np.linalg.norm(a.lab[1:] - b.lab[1:]))
