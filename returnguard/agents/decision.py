"""Decision agent: combines independent evidence into an evidence-weighted risk
score (0-100) and a routed verdict, and writes the reviewer-facing report.

Each piece of evidence adds or subtracts log-odds; the total goes through a
sigmoid. The weights are set by hand from what each signal can and cannot
prove (they are not fitted, the dataset is far too small for that), and every
contribution is returned so a reviewer can see exactly why a score is what it is.
The score is a ranking signal, not a calibrated probability."""
import math

from returnguard import config


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


IDENTITY_WEIGHTS = {
    "verified_unit": (-3.0, "Serial/batch number on the label matches the delivered unit"),
    "verified_model": (-0.5, "Model number matches, but no unit-level number could be compared"),
    "mismatch": (5.0, "Printed identifiers differ from the delivered unit"),
    "label_missing": (4.0, "The label recorded at delivery is missing from the returned item"),
    "inconclusive": (0.0, "Label could not be read clearly enough to compare"),
}


def _evidence(state: dict) -> list[dict]:
    ev = []
    screen = state.get("screen")
    if screen:
        if screen["verdict"] == "clear_mismatch":
            ev.append({"source": "visual_screen", "weight": 6.0,
                       "finding": f"Returned object does not look like the delivered product "
                                  f"(shape similarity {screen['shape_mean']:.2f})"})
        else:
            w = _clip((0.90 - screen["shape_mean"]) * 25, -2.5, 4.0)
            ev.append({"source": "visual_screen", "weight": round(w, 2),
                       "finding": f"Shape similarity {screen['shape_mean']:.2f} across 3 views "
                                  f"(lowest view {screen['shape_min']:.2f})"})
        cw = _clip((screen["color_shift_median"] - 2.8) * 1.2, -1.0, 2.5)
        ev.append({"source": "visual_screen", "weight": round(cw, 2),
                   "finding": f"Colour shift {screen['color_shift_median']:.1f} ΔE "
                              f"({'consistent' if screen['color_shift_median'] <= 2.8 else 'product colour differs'})"})

    identity = state.get("identity")
    if identity and identity.get("outcome"):
        w, text = IDENTITY_WEIGHTS[identity["outcome"]]
        ev.append({"source": "identity_agent", "weight": w, "finding": text})

    insp = state.get("inspection")
    if insp:
        c = insp["confidence"] / 100
        if insp["overall"] == "same_unit":
            w, text = -(1.0 + 3.0 * c), f"Inspector: same unit ({insp['confidence']}% confident)"
        elif insp["overall"] == "different_unit":
            w, text = 1.0 + 4.0 * c, f"Inspector: different unit ({insp['confidence']}% confident)"
        else:
            w, text = 0.5, "Inspector: inconclusive"
        ev.append({"source": "visual_inspector", "weight": round(w, 2), "finding": text})
        if insp["wear_change"] == "new_damage":
            ev.append({"source": "visual_inspector", "weight": 1.5,
                       "finding": "Damage visible at return that is not in the delivery photos"})
        elif insp["wear_change"] == "less_wear_than_delivered" and insp["overall"] != "different_unit":
            ev.append({"source": "visual_inspector", "weight": 1.5,
                       "finding": "Returned item shows less wear than the unit that was delivered"})
        if insp["reason_consistency"] == "inconsistent":
            ev.append({"source": "visual_inspector", "weight": 1.0,
                       "finding": "Photos do not support the customer's stated return reason"})
    return ev


def decide(state: dict) -> dict:
    quality = state.get("quality", {})
    bad = {a: q for a, q in quality.items() if not q["ok"]}
    if bad:
        return {"decision": "RETAKE_REQUIRED", "risk_score": None, "basis": "capture_quality", "evidence": [],
                "headline": "Return photos can't be used as evidence",
                "summary": " ".join(f"{a.capitalize()}: {q['problem']}" for a, q in bad.items()),
                "actions": ["Retake the flagged photos and resubmit the return."]}

    policy = state.get("policy", {})
    if policy and not policy["eligible"]:
        return {"decision": "REJECT", "risk_score": None, "basis": "policy", "evidence": [],
                "headline": "Return is outside the return policy", "summary": " ".join(policy["notes"]),
                "actions": ["Inform the customer of the return window."]}

    history = state.get("history") or {"accept_below": config.ACCEPT_BELOW, "reject_from": config.REJECT_FROM,
                                       "tier": "new"}
    evidence = _evidence(state)
    total = sum(e["weight"] for e in evidence)
    risk = int(round(100 / (1 + math.exp(-total))))

    if risk < history["accept_below"]:
        decision = "ACCEPT"
    elif risk >= history["reject_from"]:
        decision = "REJECT"
    else:
        decision = "HUMAN_REVIEW"

    fraud_type, rule = classify(state)
    if rule and decision == "ACCEPT":
        # rules can only raise scrutiny: a worn or damaged-after-delivery item is the
        # same unit, so its looks-based score is low, but the refund still needs a person
        decision = "HUMAN_REVIEW"
        risk = max(risk, history["accept_below"])
        evidence.append({"source": "decision_rules", "weight": 0.0, "finding": rule})

    failed = [c["agent"] for c in state.get("llm_calls", []) if not c["ok"]]
    if failed and decision == "ACCEPT" and (state.get("screen") or {}).get("verdict") != "strong_match":
        decision = "HUMAN_REVIEW"   # fail safe: never auto-accept when a needed check could not run
        evidence.append({"source": "system", "weight": 0.0,
                         "finding": f"{', '.join(failed)} unavailable; sent to a human instead of auto-accepting"})
    elif failed:
        evidence.append({"source": "system", "weight": 0.0,
                         "finding": f"{', '.join(failed)} unavailable; decided on the remaining evidence"})

    llm_used = any(c["ok"] for c in state.get("llm_calls", []))
    basis = "visual_screen" if not llm_used and not failed else "multi_agent"
    return {"decision": decision, "risk_score": risk, "basis": basis, "evidence": evidence,
            "fraud_type": fraud_type if decision != "ACCEPT" else None,
            "thresholds": {"accept_below": history["accept_below"], "reject_from": history["reject_from"]},
            **_narrative(decision, fraud_type, evidence, state)}


FRAUD_TYPES = {
    "substitution": "Returned item is not the unit that was delivered",
    "label_removed": "The label recorded at delivery is gone from the returned item",
    "wardrobing": "Item appears to have been used or worn, then returned",
    "false_damage_claim": "Damage claim contradicted by the delivery photos",
    "damage_after_delivery": "Returned with damage that happened after delivery",
}


def classify(state: dict) -> tuple[str | None, str | None]:
    """Which kind of abuse the evidence points to, plus a review rule for the kinds
    a looks-based score can't catch (the returned item is the genuine unit)."""
    insp = state.get("inspection") or {}
    ident = (state.get("identity") or {}).get("outcome")
    screen = state.get("screen") or {}
    reason = (state.get("policy") or {}).get("reason")
    category = (state.get("order") or {}).get("category")

    if screen.get("verdict") == "clear_mismatch" or ident == "mismatch" or insp.get("overall") == "different_unit":
        return "substitution", None
    if ident == "label_missing":
        return "label_removed", None
    if insp.get("tags_status") == "removed_or_cut":
        return "wardrobing", "Tags attached at delivery are missing or cut: item was likely worn"
    if insp.get("signs_of_use") and category in config.WEAR_CHECK_CATEGORIES:
        return "wardrobing", "Signs of wear after delivery: " + "; ".join(insp["signs_of_use"][:3])
    if insp.get("wear_change") == "new_damage":
        if reason == "damaged":
            return "false_damage_claim", "Customer says it arrived damaged, but the delivery photos show no damage"
        if reason != "defective":
            return "damage_after_delivery", "Returned with damage that is not in the delivery photos"
    return None, None


def _narrative(decision: str, fraud_type: str | None, evidence: list[dict], state: dict) -> dict:
    if decision != "ACCEPT" and fraud_type:
        headline = FRAUD_TYPES[fraud_type]
    else:
        headline = {
            "ACCEPT": "Returned item matches the delivered unit",
            "HUMAN_REVIEW": "Evidence is mixed: a reviewer should decide",
            "REJECT": "Returned item is not the unit that was delivered",
        }[decision]
    strongest = sorted(evidence, key=lambda e: abs(e["weight"]), reverse=True)[:3]
    summary = "; ".join(e["finding"] for e in strongest) + "."
    insp = state.get("inspection")
    if insp and insp.get("evidence_summary"):
        summary += " " + insp["evidence_summary"]

    actions = []
    if decision == "ACCEPT":
        actions.append("Approve the refund.")
    elif decision == "HUMAN_REVIEW":
        actions.append("Compare the delivery and return photos side by side, starting with the findings above.")
    else:
        actions.append("Hold the refund and share this report with the seller as dispute evidence.")
    policy = state.get("policy") or {}
    if policy.get("requires_functional_test") and decision != "REJECT":
        actions.append("Run a functional test before restocking.")
    history = state.get("history") or {}
    if history.get("tier") == "repeat_flagged":
        actions.append(f"Customer has {history['prior_flagged']} earlier flagged return(s); stricter cut-off applied.")
    return {"headline": headline, "summary": summary, "actions": actions}
