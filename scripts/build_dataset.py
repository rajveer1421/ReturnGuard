"""Build the paired evaluation dataset from the raw item photos.

Input:  Dataset/items/<item>/<front|back|side>.jpeg          photo set 1 of every item
        Dataset/items/<item>/set2/<front|back|side>.jpeg     optional second, independent photo set
                                                             (an angle missing in set2 falls back to set 1)
Output: Dataset/{same,different}/{delivery_images,return_images}/{front,back,side}/<pair_id>.jpeg
        Dataset/pairs.csv

Genuine ("same") pairs come in two kinds:
- simulated re-capture: set-1 photos, with the return side given a different rotation,
  zoom, framing, exposure, white balance, blur and JPEG quality. Easy: it is the same photo.
- real re-capture: delivery photos from one set, return photos from the other set, taken
  separately (different place, angle, lighting). No digital changes. This is the honest test.
Fraud ("different") pairs: every ordered pair of different items, set-1 photos, with the same
simulated capture noise on the return side, so the classes differ only by the item.

Pair IDs and seeds of earlier pairs never change when items are added, so results stay comparable.
"""
import csv
import io
import random
import shutil
import sys
from itertools import permutations
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "Dataset"
ANGLES = ("front", "back", "side")
RECAPTURES_PER_ITEM = 3
MAX_SIDE = 1024

ITEMS = {
    "speaker_A": {"category": "speaker", "model": "portronics_sounddrum_1", "note": "clean blue unit with bottom label"},
    "speaker_B": {"category": "speaker", "model": "portronics_sounddrum_1", "note": "worn black unit, rusted grille, label missing"},
    "shaker_A": {"category": "shaker", "model": "shaker_green_lid", "note": "green flip lid with carry loop"},
    "shaker_B": {"category": "shaker", "model": "shaker_black_lid", "note": "black lid, storage compartment"},
    "bottle_A": {"category": "bottle", "model": "steel_bottle_1l", "note": "plain steel bottle"},
    "bottle_B": {"category": "bottle", "model": "steel_bottle_1l", "note": "same model with strap and small dents"},
    # added later: appended so the IDs and seeds of the pairs above stay the same
    "headphones_blue": {"category": "headphones", "model": "sony_overear_anc", "note": "blue unit, two photo sets"},
    "headphones_black": {"category": "headphones", "model": "sony_overear_anc", "note": "black, worn unit of the same design"},
}
ORIGINAL_ITEMS = list(ITEMS)[:6]


def photo_path(item, angle, photo_set=1):
    if photo_set == 2:
        p = DATASET / "items" / item / "set2" / f"{angle}.jpeg"
        if p.exists():
            return p
    return DATASET / "items" / item / f"{angle}.jpeg"


def has_second_set(item):
    return (DATASET / "items" / item / "set2").is_dir()


def load(item, angle, photo_set=1):
    img = ImageOps.exif_transpose(Image.open(photo_path(item, angle, photo_set))).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return img


def simulate_recapture(img, rng):
    """Return a plausible second photo of the same physical scene."""
    w, h = img.size
    edges = np.array(img)[[0, -1]].reshape(-1, 3)  # top and bottom rows ~ floor/background colour
    fill = tuple(int(c) for c in np.median(edges, axis=0))

    img = img.rotate(rng.uniform(-12, 12), resample=Image.BICUBIC, fillcolor=fill)

    scale = rng.uniform(0.88, 1.08)
    dx, dy = rng.uniform(-0.05, 0.05) * w, rng.uniform(-0.05, 0.05) * h
    cw, ch = w / scale, h / scale
    left, top = (w - cw) / 2 + dx, (h - ch) / 2 + dy
    canvas = Image.new("RGB", (int(cw), int(ch)), fill)
    canvas.paste(img, (int(-left), int(-top)))
    img = canvas.resize((w, h), Image.LANCZOS)

    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.8, 1.2))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.85, 1.15))
    img = ImageEnhance.Color(img).enhance(rng.uniform(0.85, 1.15))
    r, g, b = img.split()
    r = r.point(lambda v, k=rng.uniform(0.94, 1.06): min(255, int(v * k)))
    b = b.point(lambda v, k=rng.uniform(0.94, 1.06): min(255, int(v * k)))
    img = Image.merge("RGB", (r, g, b))

    if rng.random() < 0.5:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.0)))

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=rng.randint(70, 90))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def pair_type(delivered, returned, real=False):
    if delivered == returned:
        return "same_item_real_recapture" if real else "same_item_recapture"
    a, b = ITEMS[delivered], ITEMS[returned]
    if a["model"] == b["model"]:
        return "same_model_other_unit"
    if a["category"] == b["category"]:
        return "same_category_other_model"
    return "different_category"


def write_pair(label, pair_id, delivered, returned, seed=None, delivery_set=1, return_set=1):
    """seed=None means real photos on both sides: no simulated capture noise."""
    rng = random.Random(seed) if seed is not None else None
    for angle in ANGLES:
        for phase, item, photo_set in (("delivery_images", delivered, delivery_set), ("return_images", returned, return_set)):
            out = DATASET / label / phase / angle
            out.mkdir(parents=True, exist_ok=True)
            img = load(item, angle, photo_set)
            if phase == "return_images" and rng is not None:
                img = simulate_recapture(img, rng)
            img.save(out / f"{pair_id}.jpeg", "JPEG", quality=92)


def main():
    for label in ("same", "different"):
        shutil.rmtree(DATASET / label, ignore_errors=True)

    rows = []
    pair_id = 0
    for item in ITEMS:                                   # simulated re-captures of set 1
        for _ in range(RECAPTURES_PER_ITEM):
            pair_id += 1
            write_pair("same", pair_id, item, item, seed=1000 + pair_id)
            rows.append(["same", pair_id, item, item, pair_type(item, item), 1, 1])
    for item in ITEMS:                                   # real re-captures across photo sets
        if not has_second_set(item):
            continue
        for d_set, r_set in ((1, 2), (2, 1)):
            pair_id += 1
            write_pair("same", pair_id, item, item, seed=None, delivery_set=d_set, return_set=r_set)
            rows.append(["same", pair_id, item, item, pair_type(item, item, real=True), d_set, r_set])

    original = list(permutations(ORIGINAL_ITEMS, 2))
    added = [p for p in permutations(ITEMS, 2) if p not in original]
    for pair_id, (d, r) in enumerate(original + added, start=1):
        write_pair("different", pair_id, d, r, seed=2000 + pair_id)
        rows.append(["different", pair_id, d, r, pair_type(d, r), 1, 1])

    with open(DATASET / "pairs.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["label", "pair_id", "delivery_item", "return_item", "pair_type", "delivery_set", "return_set"])
        writer.writerows(rows)

    counts = {}
    for row in rows:
        counts[row[4]] = counts.get(row[4], 0) + 1
    print(f"{len(rows)} pairs -> {DATASET}")
    for k, v in counts.items():
        print(f"  {k:28s} {v}")


if __name__ == "__main__":
    sys.exit(main())
