from returnguard import config
from returnguard.agents.decision import decide
from returnguard.pipeline import after_identity, after_triage

OK_QUALITY = {a: {"ok": True, "problem": None} for a in config.ANGLES}
POLICY_OK = {"eligible": True, "reason": "changed_mind", "notes": [], "requires_functional_test": False}
NEW_CUSTOMER = {"tier": "new", "accept_below": 50, "reject_from": 90, "prior_flagged": 0}


def screen(shape, color=1.5, verdict=None):
    if verdict is None:
        verdict = "clear_mismatch" if shape < config.FAST_REJECT_SHAPE else "strong_match" if shape >= 0.92 else "ambiguous"
    return {"shape_mean": shape, "shape_min": shape, "color_shift_median": color, "verdict": verdict}


def state(**kw):
    base = {"quality": OK_QUALITY, "policy": POLICY_OK, "history": NEW_CUSTOMER, "llm_calls": [],
            "order": {"category": "electronics", "fingerprint": None}}
    base.update(kw)
    return base


def inspection(overall="same_unit", confidence=90, **kw):
    d = {"overall": overall, "confidence": confidence, "wear_change": "none", "reason_consistency": "not_applicable",
         "signs_of_use": [], "tags_status": "not_applicable", "evidence_summary": "", "accessories_change": ""}
    d.update(kw)
    return d


def test_unusable_photo_asks_for_retake():
    q = dict(OK_QUALITY, side={"ok": False, "problem": "Photo is too blurry"})
    assert decide(state(quality=q))["decision"] == "RETAKE_REQUIRED"


def test_outside_return_window_is_a_policy_reject():
    d = decide(state(policy={**POLICY_OK, "eligible": False, "notes": ["Requested 12 days after delivery"]}))
    assert d["decision"] == "REJECT" and d["basis"] == "policy" and d["risk_score"] is None


def test_clearly_different_product_is_rejected_without_llm():
    d = decide(state(screen=screen(0.45)))
    assert d["decision"] == "REJECT" and d["fraud_type"] == "substitution" and d["basis"] == "visual_screen"


def test_strong_match_is_accepted():
    d = decide(state(screen=screen(0.98)))
    assert d["decision"] == "ACCEPT" and d["risk_score"] < 50


def test_missing_label_on_same_looking_unit_is_rejected():
    d = decide(state(screen=screen(0.85, color=3.9), identity={"outcome": "label_missing"}))
    assert d["decision"] == "REJECT" and d["fraud_type"] == "label_removed"


def test_worn_garment_is_never_auto_accepted():
    s = state(screen=screen(0.98), order={"category": "apparel", "fingerprint": None},
              inspection=inspection("same_unit", 95, signs_of_use=["makeup mark on the neckline"]))
    d = decide(s)
    assert d["decision"] == "HUMAN_REVIEW" and d["fraud_type"] == "wardrobing"


def test_cut_tags_trigger_wardrobing_for_any_category():
    d = decide(state(screen=screen(0.98), inspection=inspection(tags_status="removed_or_cut")))
    assert d["decision"] == "HUMAN_REVIEW" and d["fraud_type"] == "wardrobing"


def test_damage_claim_contradicted_by_delivery_photos():
    s = state(screen=screen(0.97), policy={**POLICY_OK, "reason": "damaged"}, inspection=inspection(wear_change="new_damage"))
    d = decide(s)
    assert d["decision"] == "HUMAN_REVIEW" and d["fraud_type"] == "false_damage_claim"


def test_failed_agent_never_leads_to_auto_accept():
    calls = [{"agent": "visual_inspector", "ok": False}]
    d = decide(state(screen=screen(0.88, color=1.0), llm_calls=calls))
    assert d["decision"] == "HUMAN_REVIEW"


def test_repeat_offender_gets_stricter_cutoff():
    strict = {**NEW_CUSTOMER, "tier": "repeat_flagged", "prior_flagged": 2, "accept_below": 30}
    s = screen(0.89, color=2.0)
    assert decide(state(screen=s))["decision"] == "ACCEPT"
    assert decide(state(screen=s, history=strict))["decision"] == "HUMAN_REVIEW"


def test_routing_skips_llm_on_clear_cases_and_reads_labels_first():
    fp = {"identifiers": [{"text": "25061502"}]}
    base = {"policy": POLICY_OK, "order": {"category": "electronics", "fingerprint": None}}
    assert after_triage({**base, "screen": screen(0.4)}) == "decide"
    assert after_triage({**base, "screen": screen(0.98)}) == "decide"
    assert after_triage({**base, "screen": screen(0.8)}) == "inspector"
    assert after_triage({**base, "screen": screen(0.98), "order": {"category": "electronics", "fingerprint": fp}}) == "identity"
    assert after_triage({**base, "screen": screen(0.98), "order": {"category": "apparel", "fingerprint": None}}) == "inspector"


def test_identity_conflicts_get_a_second_opinion():
    order = {"category": "electronics"}
    assert after_identity({"identity": {"outcome": "label_missing"}, "screen": screen(0.85), "order": order}) == "decide"
    assert after_identity({"identity": {"outcome": "label_missing"}, "screen": screen(0.98), "order": order}) == "inspector"
    assert after_identity({"identity": {"outcome": "verified_unit"}, "screen": screen(0.98), "order": order}) == "decide"
    assert after_identity({"identity": {"outcome": "verified_unit"}, "screen": screen(0.85), "order": order}) == "inspector"
