"""Identity agent: reads printed identifiers (serial / batch / model numbers).

Delivery: record every identifier and where it is ("fingerprint").
Return:   a *blind* read. The agent is told where labels were, but never what
          they said, so it cannot simply agree with the expected text. The
          comparison is done in code with fuzzy matching.

This is the check that catches a same-model swap: two units of one model look
identical to an embedding, but their batch or serial numbers differ, or the
label is gone from a worn unit.
"""
import re
from difflib import SequenceMatcher

from returnguard import config, llm
from returnguard.schemas import ProductFingerprint, ReturnReadout

UNIT_LEVEL = {"serial_number", "batch_number", "barcode"}
MATCH_RATIO = 0.80
MISMATCH_RATIO = 0.50

FINGERPRINT_SYSTEM = """You are the delivery-time identity agent of an e-commerce return-verification system.
You receive three photos (front, back, side) of ONE product unit, taken at the moment it is handed to the customer.
Background was removed automatically; ignore the grey background.

Record everything that could later prove whether a returned item is this exact unit:
- identifiers: transcribe printed text EXACTLY as printed: serial / batch / lot numbers, barcodes digits, model
  numbers, brand and model names on labels or stickers. Copy each character; write '?' for any character you
  cannot read with certainty. Never guess or complete text. Ignore button symbols and icons.
- distinctive_marks: unit-specific wear or features (scratches, dents, rust, stains, stickers, faded paint), with
  where they are. If the unit looks new, return an empty list.
- accessories: removable parts visible in the photos (strap, lid, cable).
- tags_attached: brand tags, price tags and tamper-evident return tags still attached, and where. A missing tag at
  return is the main evidence that clothing was worn and sent back.
Only report what is visible in these photos."""

READOUT_SYSTEM = """You are the return-time identity agent of an e-commerce return-verification system.
You receive three photos (front, back, side) of an item a customer is returning. Background was removed
automatically; ignore the grey background.

When the product was delivered, it carried printed labels at the locations listed below. For each location:
1. location_visible: is that part of the product clearly visible in these photos?
2. label_present: if visible, is there any printed label or text there now?
3. transcribed_text: transcribe EXACTLY the text you can read there ('' if none). Write '?' for characters you
   cannot read with certainty. Never guess.
Read only what is in these photos. You are not told what the labels said, on purpose."""


def _photos(cutouts: dict) -> list[dict]:
    parts = []
    for angle in config.ANGLES:
        parts += [llm.text_part(f"{angle.upper()} view:"), llm.image_part(cutouts[angle])]
    return parts


def fingerprint(delivery_cutouts: dict) -> tuple[ProductFingerprint, llm.CallRecord]:
    return llm.call_structured("identity_fingerprint", ProductFingerprint, FINGERPRINT_SYSTEM, _photos(delivery_cutouts))


def label_locations(fp: dict) -> list[dict]:
    """Group the delivery identifiers by where they are on the product."""
    groups: dict[tuple, dict] = {}
    for ident in fp.get("identifiers", []):
        key = (ident["view"], ident["location"].strip().lower())
        groups.setdefault(key, {"view": ident["view"], "location": ident["location"], "identifiers": []})
        groups[key]["identifiers"].append(ident)
    return list(groups.values())


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9?]", "", text.upper())


def text_match(expected: str, observed: str) -> float:
    """Best fuzzy match of `expected` against any stretch of `observed` (0..1).
    '?' (unreadable) characters are dropped from both sides."""
    e, o = _norm(expected).replace("?", ""), _norm(observed).replace("?", "")
    if not e or not o:
        return 0.0
    if e in o:
        return 1.0
    best = SequenceMatcher(None, e, o).ratio() if len(o) <= len(e) else 0.0
    for i in range(0, max(1, len(o) - len(e) + 1)):
        best = max(best, SequenceMatcher(None, e, o[i:i + len(e)]).ratio())
    return best


def compare(locations: list[dict], readout: ReturnReadout) -> dict:
    """Deterministic comparison of the blind readout against the delivery record."""
    by_id = {r.location_id: r for r in readout.readings}
    results = []
    for loc_id, loc in enumerate(locations):
        reading = by_id.get(loc_id)
        checks = []
        brand_only = all(i["kind"] == "brand_name" for i in loc["identifiers"])
        if reading is None or not reading.location_visible:
            status = "not_visible"
        elif not reading.label_present or not _norm(reading.transcribed_text).replace("?", ""):
            # a printed logo is easily lost to glare or angle; only a missing *label* is evidence
            status = "not_visible" if brand_only else "missing"
        else:
            for ident in loc["identifiers"]:
                score = text_match(ident["text"], reading.transcribed_text)
                checks.append({"kind": ident["kind"], "expected": ident["text"], "score": round(score, 2),
                               "status": "match" if score >= MATCH_RATIO else "mismatch" if score < MISMATCH_RATIO else "partial"})
            unit = [c for c in checks if c["kind"] in UNIT_LEVEL]
            model = [c for c in checks if c["kind"] not in UNIT_LEVEL and c["kind"] != "brand_name"]
            brand = [c for c in checks if c["kind"] == "brand_name"]
            decisive = unit or model or brand   # strongest identifier present decides
            if any(c["status"] == "match" for c in decisive):
                status = "unit_match" if unit and any(c["status"] == "match" for c in unit) else "model_match"
                # a matching model number but a clearly different batch/serial is still a swap
                if unit and all(c["status"] == "mismatch" for c in unit):
                    status = "mismatch"
            elif decisive and all(c["status"] == "mismatch" for c in decisive):
                status = "mismatch"
            else:
                status = "inconclusive"
        results.append({"location": loc["location"], "view": loc["view"], "status": status,
                        "expected": [i["text"] for i in loc["identifiers"]],
                        "expected_kinds": [{"kind": i["kind"], "text": i["text"]} for i in loc["identifiers"]],
                        "observed": reading.transcribed_text if reading else "", "checks": checks})

    statuses = {r["status"] for r in results}
    if "missing" in statuses:
        outcome = "label_missing"
    elif "mismatch" in statuses:
        outcome = "mismatch"
    elif "unit_match" in statuses:
        outcome = "verified_unit"
    elif "model_match" in statuses:
        outcome = "verified_model"
    else:
        outcome = "inconclusive"
    return {"outcome": outcome, "locations": results, "other_text_seen": readout.other_text_seen}


def verify(fp: dict, return_cutouts: dict) -> tuple[dict, llm.CallRecord]:
    locations = label_locations(fp)
    listing = "\n".join(f"- location_id {i}: {loc['location']} (seen in the {loc['view']} view at delivery)"
                        for i, loc in enumerate(locations))
    parts = [llm.text_part("Label locations recorded at delivery:\n" + listing)] + _photos(return_cutouts)
    readout, rec = llm.call_structured("identity_verify", ReturnReadout, READOUT_SYSTEM, parts)
    return compare(locations, readout), rec
