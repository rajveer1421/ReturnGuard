from returnguard.agents.identity import compare, label_locations, text_match
from returnguard.schemas import LocationReading, ReturnReadout

FINGERPRINT = {"identifiers": [
    {"kind": "brand_name", "text": "PORTRONICS", "view": "back", "location": "label on the base"},
    {"kind": "model_number", "text": "POR 1327", "view": "back", "location": "label on the base"},
    {"kind": "batch_number", "text": "25061502", "view": "back", "location": "label on the base"},
]}


def readout(visible=True, present=True, text=""):
    return ReturnReadout(readings=[LocationReading(location_id=0, location_visible=visible, label_present=present,
                                                   transcribed_text=text)], other_text_seen=[])


def test_text_match_tolerates_ocr_noise():
    assert text_match("25061502", "Batch No.: 25061502") == 1.0
    assert text_match("POR 1327", "Model No.: POR1327") == 1.0
    assert text_match("25061502", "Batch 2506I502") >= 0.8      # one misread character
    assert text_match("25061502", "Batch 99887766") < 0.5


def test_identifiers_grouped_by_location():
    locs = label_locations(FINGERPRINT)
    assert len(locs) == 1 and len(locs[0]["identifiers"]) == 3


def test_batch_number_match_verifies_unit_despite_misread_brand():
    out = compare(label_locations(FINGERPRINT), readout(text="PORTIONICS POR 1327 Batch No. 25061502"))
    assert out["outcome"] == "verified_unit"
    assert out["locations"][0]["expected"] == ["PORTRONICS", "POR 1327", "25061502"]


def test_same_model_different_batch_is_a_mismatch():
    out = compare(label_locations(FINGERPRINT), readout(text="POR 1327 Batch 77441190"))
    assert out["outcome"] == "mismatch"


def test_brand_only_logo_gives_weak_evidence():
    logo = label_locations({"identifiers": [{"kind": "brand_name", "text": "SONY", "view": "side", "location": "headband slider"}]})
    assert compare(logo, readout(text="SONY"))["outcome"] == "verified_model"
    assert compare(logo, readout(text="boAt"))["outcome"] == "mismatch"
    # a logo lost to glare or angle is not evidence of a swap
    assert compare(logo, readout(present=False))["outcome"] == "inconclusive"


def test_label_gone_is_missing_and_hidden_label_is_inconclusive():
    assert compare(label_locations(FINGERPRINT), readout(present=False))["outcome"] == "label_missing"
    assert compare(label_locations(FINGERPRINT), readout(visible=False))["outcome"] == "inconclusive"
