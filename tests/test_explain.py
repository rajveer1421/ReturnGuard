"""The plain-language layer must say what each number means, in words a reviewer understands."""
from returnguard import explain


def test_shape_and_colour_are_explained_with_normal_ranges():
    assert explain.shape(0.97)["verdict"] == "Matches the delivered item"
    assert explain.shape(0.80)["level"] == "warn" and "72–85%" in explain.shape(0.80)["detail"]
    assert explain.shape(0.45)["verdict"] == "A different product"
    assert explain.shape(0.851)["value"] == "85% similar"

    ok = explain.colour(2.1)
    assert ok["level"] == "good" and "normal: under 2.8" in ok["value"]
    off = explain.colour(3.9)
    assert off["verdict"] == "Colour is slightly off" and "3.9" in off["value"]
    assert explain.colour(6.0)["verdict"] == "Clearly a different colour"


def test_missing_label_is_explained_with_what_was_expected():
    ident = {"outcome": "label_missing", "locations": [{
        "location": "round label on the base", "view": "back", "status": "missing", "observed": "",
        "expected": ["PORTRONICS", "Batch No.: 25061502"], "checks": []}]}
    e = explain.identity(ident)
    assert e["level"] == "bad" and "found no label" in e["detail"] and "25061502" in e["detail"]


def test_quota_errors_become_plain_sentences():
    msg = explain.llm_error_text("GoogleRateLimitError: 429 RESOURCE_EXHAUSTED quota")
    assert "free daily limit" in msg
    assert "denied access" in explain.llm_error_text("403 PERMISSION_DENIED")


def test_gemini_verdict_is_always_present_even_when_not_needed():
    result = {
        "decision": {"decision": "REJECT", "risk_score": 99, "basis": "visual_screen", "evidence": [
            {"source": "visual_screen", "weight": 6.0, "finding": "Returned object does not look like the delivered product"}],
            "thresholds": {"accept_below": 50, "reject_from": 90}, "actions": []},
        "screen": {"verdict": "clear_mismatch", "shape_mean": 0.42, "shape_min": 0.4, "color_shift_median": 5.0,
                   "shape": {"front": 0.4, "back": 0.42, "side": 0.44}, "color_shift": {"front": 5, "back": 5, "side": 5}},
        "policy": {"eligible": True, "category": "electronics", "days_since_delivery": 2, "window_days": 7,
                   "requires_functional_test": True},
        "history": {"tier": "new", "prior_returns": 0, "prior_flagged": 0, "accept_below": 50, "reject_from": 90},
        "llm_calls": [], "route": ["intake", "policy", "history", "screen", "triage", "decide"],
    }
    x = explain.explain_result(result, {"fingerprint": {"identifiers": [{"text": "25061502"}]}})
    agents = {g["agent"]: g for g in x["gemini"]}
    assert agents["Visual inspection"]["status"] == "not_needed"
    assert "completely different product" in agents["Visual inspection"]["detail"]
    assert x["decision"]["sentence"].startswith("Hold the refund")
    assert any(c["name"] == "Shape match" and c["verdict"] == "A different product" for c in x["checks"])
    assert x["evidence"][0]["effect"] == "strongly points to fraud"
