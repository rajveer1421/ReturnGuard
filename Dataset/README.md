# Dataset

Raw photos live in `items/`; the paired evaluation set (`same/`, `different/`, `pairs.csv`) is generated from them by
`python scripts/build_dataset.py` and is not committed.

## Raw photos: `items/`

```
items/<item>/front.jpeg, back.jpeg, side.jpeg          photo set 1
items/<item>/set2/front.jpeg, back.jpeg, side.jpeg     photo set 2, taken separately (only some items)
```

| Item | What it is | Photo sets |
|---|---|---|
| speaker_A | clean blue Portronics speaker with a batch label on the base | 1 |
| speaker_B | same model, worn black unit, label gone | 1 |
| shaker_A / shaker_B | two different shaker bottles | 1 |
| bottle_A / bottle_B | same steel bottle model; B has a strap and small dents | 1 |
| headphones_blue | blue Sony over-ear headphones | 2 |
| headphones_black | black, worn Sony headphones of the same design | 2 (set 2 has a new front photo only; back and side reuse set 1) |

Angles: **front** = the main view (earcups facing the camera, product upright), **back** = the reverse / underside
view, **side** = the side profile (for headphones: the slider arm with the SONY logo).

## Pairs: `same/` and `different/`

```
<same|different>/delivery_images/<front|back|side>/<pair_id>.jpeg
<same|different>/return_images/<front|back|side>/<pair_id>.jpeg
```

**Pair IDs are numbered separately in each folder.** `same/.../25.jpeg` and `different/.../25.jpeg` are unrelated
pairs. Within one pair, the delivery and return files share the same number. `pairs.csv` lists every pair:
`label, pair_id, delivery_item, return_item, pair_type, delivery_set, return_set`.

| Folder | IDs | Contents |
|---|---|---|
| same | 1–18 | the first 6 items, 3 pairs each: return photo = the delivery photo, digitally re-captured (rotation, zoom, exposure, white balance, blur, JPEG) |
| same | 19–24 | the headphones, the same way |
| same | 25–28 | **real** re-photographs: delivery from one photo set, return from the other (25 & 27: set 1 → set 2; 26 & 28: set 2 → set 1). They look different on purpose |
| different | 1–30 | every ordered pair of the first 6 items |
| different | 31–56 | every new ordered pair involving the headphones |

Return images in `different/` get the same simulated re-capture as in `same/`, so the two classes differ only by the
item. Seeds are fixed: rebuilding produces byte-identical files, and adding items never changes existing pairs.
