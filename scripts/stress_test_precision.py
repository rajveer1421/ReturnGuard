"""Precision stress test: how often are GENUINE returns flagged when the return photo is
taken differently?

Precision = TP / (TP + FP) only drops when a genuine customer's return is flagged, so this
test changes *how the returned item is photographed* (one augmentation type at a time, at a
mild and a strong level) and measures the false flags. Fraud pairs are scored under the same
augmentation, so precision per condition is exact, not estimated.

Only the return side is augmented. One augmented photo set per item therefore serves both its
genuine pair (X -> X) and every fraud pair in which X is the returned item (Y -> X): per
condition, 8 genuine + 56 fraud pairs from 24 augmented photos.

This runs the free local stage (background removal, quality gate, object-only DINOv2, colour,
evidence-weighted decision) with no LLM calls. For each genuine return it also records what the
full pipeline would do next: fast-accept, send to Gemini, or fast-reject (a hard false
rejection no LLM can undo).

    python scripts/stress_test_precision.py
"""
import json
import math
import random
import sys
import time
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_dataset import ANGLES, ITEMS, has_second_set, load  # noqa: E402
from returnguard import imaging  # noqa: E402
from returnguard.agents import decision  # noqa: E402
from returnguard.agents.screen import visual_screen  # noqa: E402
from returnguard.embeddings import view_features  # noqa: E402

CATEGORY = {"speaker": "electronics", "headphones": "electronics", "shaker": "home_kitchen", "bottle": "home_kitchen"}
FRAUD_PREVALENCE = 0.15   # Appriss Retail 2024: 15.14% of returns were fraudulent (US); used for "implied precision"
RESULTS = ROOT / "results"


# ── augmentations ──────────────────────────────────────────────────────────
def _fill(img):
    edges = np.array(img)[[0, -1]].reshape(-1, 3)
    return tuple(int(c) for c in np.median(edges, axis=0))


def rotate(img, rng, deg):
    return img.rotate(rng.choice([-1, 1]) * deg, resample=Image.BICUBIC, fillcolor=_fill(img))


def perspective(img, rng, amount):
    """Viewpoint tilt: one edge of the frame comes closer to the camera than the opposite edge."""
    w, h = img.size
    d = amount * min(w, h)
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    side = rng.choice(["top", "bottom", "left", "right"])
    dst = {"top": [(d, 0), (w - d, 0), (w, h), (0, h)], "bottom": [(0, 0), (w, 0), (w - d, h), (d, h)],
           "left": [(0, d), (w, 0), (w, h), (0, h - d)], "right": [(0, 0), (w, d), (w, h - d), (0, h)]}[side]
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):            # PIL maps output -> input pixels
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        rhs += [u, v]
    coeffs = np.linalg.solve(np.array(rows, float), np.array(rhs, float))
    return img.transform(img.size, Image.PERSPECTIVE, tuple(coeffs), Image.BICUBIC, fillcolor=_fill(img))


def zoom_out(img, rng, scale):
    """Photo taken from further away: the product is smaller in the frame."""
    w, h = img.size
    small = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), _fill(img))
    dx = int(rng.uniform(0.2, 0.8) * (w - small.width))
    dy = int(rng.uniform(0.2, 0.8) * (h - small.height))
    canvas.paste(small, (dx, dy))
    return canvas


def crop_cut(img, rng, frac):
    """Product partly out of frame: one side cut off, then the photo is the usual size again."""
    w, h = img.size
    side = rng.choice(["top", "bottom", "left", "right"])
    box = {"top": (0, int(h * frac), w, h), "bottom": (0, 0, w, int(h * (1 - frac))),
           "left": (int(w * frac), 0, w, h), "right": (0, 0, int(w * (1 - frac)), h)}[side]
    return img.crop(box).resize((w, h), Image.LANCZOS)


def brightness(img, rng, f):
    return ImageEnhance.Brightness(img).enhance(f)


def contrast(img, rng, f):
    return ImageEnhance.Contrast(img).enhance(f)


def white_balance(img, rng, red, blue):
    arr = np.array(img, dtype=np.float32)
    arr[..., 0] *= red
    arr[..., 2] *= blue
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def shadow(img, rng, strength):
    """A soft shadow falling across the scene (multiplicative gradient)."""
    w, h = img.size
    ang = rng.uniform(0, 2 * math.pi)
    yy, xx = np.mgrid[0:h, 0:w]
    t = ((xx - w / 2) * math.cos(ang) + (yy - h / 2) * math.sin(ang)) / (0.5 * math.hypot(w, h))
    mult = 1 - strength * np.clip((t + 0.2) / 0.8, 0, 1)
    return Image.fromarray(np.clip(np.array(img, np.float32) * mult[..., None], 0, 255).astype(np.uint8))


def glare(img, rng, strength):
    """A bright reflection (e.g. a ceiling light) over part of the product."""
    w, h = img.size
    r = int(min(w, h) * 0.18)
    cx, cy = int(w * rng.uniform(0.35, 0.65)), int(h * rng.uniform(0.3, 0.6))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((cx - r, cy - int(r * 0.6), cx + r, cy + int(r * 0.6)), fill=255)
    m = np.array(mask.filter(ImageFilter.GaussianBlur(r * 0.5)), np.float32)[..., None] / 255 * strength
    arr = np.array(img, np.float32)
    return Image.fromarray(np.clip(arr * (1 - m) + 255 * m, 0, 255).astype(np.uint8))


def gaussian_blur(img, rng, radius):
    return img.filter(ImageFilter.GaussianBlur(radius))


def motion_blur(img, rng, length):
    """Camera shake: average along one direction over `length` pixels."""
    arr = np.array(img, np.float32)
    axis = rng.choice([0, 1])
    pad = [(0, 0)] * 3
    pad[axis] = (length // 2, length - length // 2)
    padded = np.pad(arr, pad, mode="edge")
    c = np.cumsum(padded, axis=axis, dtype=np.float64)
    c = np.concatenate([np.zeros_like(np.take(c, [0], axis=axis)), c], axis=axis)
    out = (np.take(c, range(length, c.shape[axis]), axis=axis) - np.take(c, range(0, c.shape[axis] - length), axis=axis)) / length
    out = np.take(out, range(arr.shape[axis]), axis=axis)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def noise(img, rng, sigma):
    nrng = np.random.default_rng(rng.randint(0, 2 ** 31))
    arr = np.array(img, np.float32) + nrng.normal(0, sigma, (img.height, img.width, 3))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def jpeg(img, rng, quality):
    import io
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def low_res(img, rng, f):
    w, h = img.size
    return img.resize((max(8, int(w * f)), max(8, int(h * f))), Image.BILINEAR).resize((w, h), Image.BICUBIC)


def occlusion(img, rng, width_frac):
    """A finger or thumb covering part of the product, entering from one edge to just past the
    centre of the frame; `width_frac` is the finger's width as a share of the photo's short side."""
    w, h = img.size
    out = img.copy()
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    skin = (214, 160, 125, 255)
    side = rng.choice(["left", "right", "bottom"])
    cy, cx = int(h * rng.uniform(0.4, 0.6)), int(w * rng.uniform(0.4, 0.6))
    # the fingertip reaches the middle of the frame, where the product is
    length = {"left": cx, "right": w - cx, "bottom": h - cy}[side] + int(0.08 * min(w, h))
    thick = max(8, int(width_frac * min(w, h)))
    if side == "left":
        box = (0, cy - thick // 2, length, cy + thick // 2)
    elif side == "right":
        box = (w - length, cy - thick // 2, w, cy + thick // 2)
    else:
        box = (cx - thick // 2, h - length, cx + thick // 2, h)
    d.rounded_rectangle(box, radius=thick // 2, fill=skin)
    layer = layer.filter(ImageFilter.GaussianBlur(2))
    out.paste(layer, mask=layer.getchannel("A"))
    return out


_BG_CACHE = {}


def _background(kind, size):
    w, h = size
    if kind == "plain":
        grad = np.linspace(0.92, 1.05, h)[:, None, None]
        bg = np.ones((h, w, 3), np.float32) * np.array([205, 196, 182], np.float32) * grad
        return Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8))
    if "cluttered" not in _BG_CACHE:
        # patterned tablecloth from one of the real photo sessions (no product in this region)
        src = Image.open(ROOT / "Dataset" / "items" / "headphones_blue" / "set2" / "front.jpeg").convert("RGB")
        _BG_CACHE["cluttered"] = src.crop((0, int(src.height * 0.82), src.width, src.height))
    tex = _BG_CACHE["cluttered"]
    scale = max(w / tex.width, h / tex.height)
    tex = tex.resize((int(tex.width * scale) + 1, int(tex.height * scale) + 1), Image.LANCZOS)
    return tex.crop((0, 0, w, h))


def background(img, rng, kind):
    """The same product photographed on a different surface (plain floor, or a busy patterned cloth)."""
    from rembg import remove
    mask = remove(img, session=imaging._rembg_session(), only_mask=True).convert("L")
    bg = _background(kind, img.size)
    return Image.composite(img, bg, mask)


CONDITIONS = [  # name, label, function, mild params, strong params
    ("rotation", "Rotated", rotate, (10,), (25,)),
    ("perspective", "Viewpoint tilt", perspective, (0.08,), (0.18,)),
    ("zoom_out", "Photographed from further away", zoom_out, (0.8,), (0.55,)),
    ("crop", "Partly out of frame", crop_cut, (0.10,), (0.25,)),
    ("darker", "Darker room", brightness, (0.7,), (0.45,)),
    ("brighter", "Overexposed", brightness, (1.35,), (1.8,)),
    ("warm", "Warm (yellow) light", white_balance, (1.08, 0.92), (1.18, 0.80)),
    ("cool", "Cool (blue) light", white_balance, (0.92, 1.08), (0.82, 1.18)),
    ("low_contrast", "Low contrast / haze", contrast, (0.7,), (0.45,)),
    ("shadow", "Shadow across the item", shadow, (0.35,), (0.65,)),
    ("glare", "Glare / reflection", glare, (0.45,), (0.8,)),
    ("blur", "Out of focus", gaussian_blur, (1.5,), (3.5,)),
    ("motion_blur", "Camera shake", motion_blur, (9,), (21,)),
    ("noise", "Sensor noise (low light)", noise, (10,), (25,)),
    ("jpeg", "Heavy JPEG compression", jpeg, (30,), (8,)),
    ("low_res", "Low resolution", low_res, (0.5,), (0.25,)),
    ("occlusion", "Finger covering part", occlusion, (0.08,), (0.14,)),
    ("background", "Different background", background, ("plain",), ("cluttered",)),
]


def seed_for(*parts) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


# ── scoring ────────────────────────────────────────────────────────────────
def features(img):
    cut = imaging.remove_background(img)
    q = imaging.assess_quality(img, cut)
    return view_features(cut), {"ok": q.ok, "problem": q.problem}


def local_decision(delivered, d_feats, r_feats, r_quality):
    screen = visual_screen(d_feats, r_feats)
    state = {"quality": r_quality, "screen": screen, "llm_calls": [],
             "policy": {"eligible": True, "reason": "changed_mind", "notes": [], "requires_functional_test": False},
             "history": {"tier": "new", "accept_below": 50, "reject_from": 90, "prior_flagged": 0},
             "order": {"category": CATEGORY[delivered.split("_")[0]], "fingerprint": None}}
    if any(not q["ok"] for q in r_quality.values()):
        screen = None
    d = decision.decide(state)
    return d["decision"], screen


def wilson(k, n, z=1.96):
    if n == 0:
        return [0.0, 0.0]
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - hw), 4), round(min(1, c + hw), 4)]


def implied_precision(tpr, fpr, prevalence=FRAUD_PREVALENCE):
    denom = tpr * prevalence + fpr * (1 - prevalence)
    return round(tpr * prevalence / denom, 4) if denom else None


def score_condition(name, label, level, returns, deliveries):
    """returns: item -> (features by angle, quality by angle)."""
    genuine, fraud = [], []
    for returned, (r_feats, r_quality) in returns.items():
        for delivered, d_feats in deliveries.items():
            dec, screen = local_decision(delivered, d_feats, r_feats, r_quality)
            row = {"delivered": delivered, "returned": returned, "decision": dec,
                   "screen": screen["verdict"] if screen else "retake",
                   "shape_mean": screen["shape_mean"] if screen else None,
                   "color_shift": screen["color_shift_median"] if screen else None}
            (genuine if delivered == returned else fraud).append(row)
    fp = sum(r["decision"] != "ACCEPT" for r in genuine)
    tp = sum(r["decision"] != "ACCEPT" for r in fraud)
    tn, fn = len(genuine) - fp, len(fraud) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / len(fraud)
    fpr = fp / len(genuine)
    f05 = (1.25 * precision * recall / (0.25 * precision + recall)) if precision + recall else 0.0
    by = lambda rows, key, val: sum(r[key] == val for r in rows)
    return {
        "condition": name, "label": label, "level": level,
        "genuine": len(genuine), "fraud": len(fraud),
        "local": {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(precision, 4),
                  "precision_ci": wilson(tp, tp + fp), "recall": round(recall, 4), "f0_5": round(f05, 4),
                  "false_flag_rate": round(fpr, 4), "false_flag_ci": wilson(fp, len(genuine)),
                  "implied_precision_at_15pct_fraud": implied_precision(recall, fpr)},
        "genuine_routing": {"fast_accept": by(genuine, "screen", "strong_match"),
                            "sent_to_gemini": by(genuine, "screen", "ambiguous"),
                            "fast_reject": by(genuine, "screen", "clear_mismatch"),
                            "retake": by(genuine, "screen", "retake")},
        "genuine_shape_min": min((r["shape_mean"] for r in genuine if r["shape_mean"] is not None), default=None),
        "genuine_pairs": genuine,
    }


def main():
    t0 = time.time()
    items = list(ITEMS)
    print(f"Precision stress test: {len(items)} items, {len(CONDITIONS)} augmentation types x 2 levels + baseline")
    deliveries = {it: {a: features(load(it, a))[0] for a in ANGLES} for it in items}

    def augmented_returns(fn, params, cname):
        out = {}
        for it in items:
            feats, quals = {}, {}
            for a in ANGLES:
                rng = random.Random(seed_for(cname, it, a, params))
                feats[a], quals[a] = features(fn(load(it, a), rng, *params))
            out[it] = (feats, quals)
        return out

    rows = [score_condition("baseline", "No change (same photo, re-encoded)", "none",
                            augmented_returns(jpeg, (92,), "baseline"), deliveries)]
    print(f"  baseline done ({time.time() - t0:.0f}s)", flush=True)
    for name, label, fn, mild, strong in CONDITIONS:
        for level, params in (("mild", mild), ("strong", strong)):
            row = score_condition(name, label, level, augmented_returns(fn, params, f"{name}-{level}"), deliveries)
            rows.append(row)
            g, l = row["genuine_routing"], row["local"]
            print(f"  {label:34s} {level:6s} genuine flagged {l['fp']}/{row['genuine']}  "
                  f"(fast-reject {g['fast_reject']}, to Gemini {g['sent_to_gemini']}, retake {g['retake']})  "
                  f"precision {l['precision']:.3f}  recall {l['recall']:.3f}  [{time.time() - t0:.0f}s]", flush=True)

    # real second photo session (headphones only): the honest version of all of the above
    real = []
    for it in [i for i in items if has_second_set(i)]:
        r_feats, r_quality = {}, {}
        for a in ANGLES:
            r_feats[a], r_quality[a] = features(load(it, a, 2))
        dec, screen = local_decision(it, deliveries[it], r_feats, r_quality)
        real.append({"item": it, "decision": dec, "screen": screen["verdict"] if screen else "retake",
                     "shape_mean": screen["shape_mean"] if screen else None,
                     "color_shift": screen["color_shift_median"] if screen else None})

    aug_rows = rows[1:]
    total_genuine = sum(r["genuine"] for r in aug_rows)
    summary = {
        "conditions": len(aug_rows),
        "genuine_returns_tested": total_genuine,
        "genuine_flagged_by_local_stage": sum(r["local"]["fp"] for r in aug_rows),
        "hard_false_rejections": sum(r["genuine_routing"]["fast_reject"] for r in aug_rows),
        "sent_to_gemini": sum(r["genuine_routing"]["sent_to_gemini"] for r in aug_rows),
        "retakes": sum(r["genuine_routing"]["retake"] for r in aug_rows),
        "fast_accepted": sum(r["genuine_routing"]["fast_accept"] for r in aug_rows),
        "fraud_prevalence_assumed_for_implied_precision": FRAUD_PREVALENCE,
    }
    results = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "stage": "local (no LLM calls)",
               "summary": summary, "conditions": rows, "real_second_session": real,
               "runtime_s": round(time.time() - t0)}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "stress_precision.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    write_markdown(results, RESULTS / "stress_precision.md")
    print(f"\nWrote {RESULTS / 'stress_precision.json'} in {time.time() - t0:.0f}s")


def write_markdown(r, path):
    s = r["summary"]
    lines = [
        "# Precision stress test (local stage, no LLM)", "",
        f"Generated {r['generated_at']}. Each condition changes only how the **returned** item is photographed; "
        "delivery photos are untouched. Per condition: 8 genuine + 56 fraud pairs (8 items). "
        "*Flagged* = not auto-accepted by the local stage (review, reject or retake).", "",
        f"Across {s['conditions']} conditions, {s['genuine_flagged_by_local_stage']} of {s['genuine_returns_tested']} "
        f"genuine returns were flagged by the local stage: {s['hard_false_rejections']} fast-rejected outright (a hard false "
        f"rejection no LLM would undo), {s['sent_to_gemini']} would be sent to Gemini, {s['retakes']} asked for a retake; "
        f"{s['fast_accepted']} were fast-accepted.", "",
        "| Augmentation | Level | Genuine flagged | Fast-reject | To Gemini | Retake | Precision (95% interval) | Recall | Implied precision at 15% fraud |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in r["conditions"]:
        l, g = c["local"], c["genuine_routing"]
        lines.append(f"| {c['label']} | {c['level']} | {l['fp']}/{c['genuine']} | {g['fast_reject']} | {g['sent_to_gemini']} | "
                     f"{g['retake']} | {l['precision'] * 100:.1f}% ({l['precision_ci'][0] * 100:.0f}–{l['precision_ci'][1] * 100:.0f}%) | "
                     f"{l['recall'] * 100:.1f}% | {(l['implied_precision_at_15pct_fraud'] or 0) * 100:.1f}% |")
    if r["real_second_session"]:
        lines += ["", "## Real second photo session (headphones)", "",
                  "| Item | Local decision | Screen | Shape | Colour ΔE |", "|---|---|---|---|---|"]
        for x in r["real_second_session"]:
            lines.append(f"| {x['item']} | {x['decision']} | {x['screen']} | {x['shape_mean']} | {x['color_shift']} |")
    lines += ["", "*Implied precision at 15% fraud* re-weights the measured false-flag rate and recall to a realistic "
              "share of fraudulent returns (Appriss Retail 2024: 15.14%), because precision depends on how common fraud is."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
