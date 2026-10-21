"""Plain-language explanations of everything the pipeline measured, for the result page
and the seller report. Nothing here changes a decision; it only translates numbers
into "what was checked, what is normal, and is this value fine or a problem".

Reference ranges come from the evaluation set (object-only DINOv2, mean of 3 views):
same item re-photographed 89-99%, another unit of the same or a similar model 72-85%,
different products 37-53%. Colour (median chroma, Delta E): same item <= 2.6,
blue vs black speaker of one model ~3.9.
"""
from returnguard import config

GOOD, OK, WARN, BAD, INFO = "good", "ok", "warn", "bad", "info"
COLOR_NORMAL_MAX = 2.8
COLOR_CLEAR_DIFF = 4.0


def risk_band(risk):
    if risk is None:
        return None
    if risk < 20:
        return {"label": "Very low risk", "level": GOOD}
    if risk < config.ACCEPT_BELOW:
        return {"label": "Low risk", "level": GOOD}
    if risk < config.REJECT_FROM:
        return {"label": "Needs a human check", "level": WARN}
    return {"label": "Very high risk", "level": BAD}


def shape(sim: float) -> dict:
    pct = round(sim * 100)
    if sim >= config.FAST_ACCEPT_SHAPE:
        return {"value": f"{pct}% similar", "verdict": "Matches the delivered item", "level": GOOD,
                "detail": "Photos of the same item usually score 89–99%."}
    if sim >= 0.85:
        return {"value": f"{pct}% similar", "verdict": "Mostly matches", "level": OK,
                "detail": "Just below the usual range for the same item (89–99%). Camera angle or a cluttered "
                          "background can cause this."}
    if sim >= config.FAST_REJECT_SHAPE:
        return {"value": f"{pct}% similar", "verdict": "Noticeably different", "level": WARN,
                "detail": "Lower than photos of the same item (89–99%). Another unit of the same or a similar "
                          "model usually scores 72–85%."}
    return {"value": f"{pct}% similar", "verdict": "A different product", "level": BAD,
            "detail": "Completely different products score 37–53%."}


def colour(delta: float) -> dict:
    value = f"difference {delta:.1f} (normal: under {COLOR_NORMAL_MAX})"
    if delta <= 1.5:
        return {"value": value, "verdict": "Same colour", "level": GOOD,
                "detail": "0 means identical. Small differences are normal: lighting and camera settings shift colour slightly."}
    if delta <= COLOR_NORMAL_MAX:
        return {"value": value, "verdict": "Same colour (normal lighting variation)", "level": GOOD,
                "detail": f"Re-photographing the same item gives up to about 2.6; anything under {COLOR_NORMAL_MAX} is normal."}
    if delta <= COLOR_CLEAR_DIFF:
        return {"value": value, "verdict": "Colour is slightly off", "level": WARN,
                "detail": f"More than lighting usually explains (normal is under {COLOR_NORMAL_MAX}). For comparison, the "
                          "blue and black speakers of the same model differ by about 3.9."}
    return {"value": value, "verdict": "Clearly a different colour", "level": BAD,
            "detail": "Far beyond what lighting can explain."}


def llm_error_text(error: str | None) -> str:
    e = error or ""
    if "RESOURCE_EXHAUSTED" in e or "429" in e or "quota" in e.lower():
        return ("Gemini's free daily limit for this API key is used up, so this check could not run. It resets every "
                "24 hours; enabling billing in Google AI Studio removes the limit.")
    if "PERMISSION_DENIED" in e or "403" in e:
        return "Google rejected the API key: its project has been denied access."
    if "NOT_FOUND" in e or "404" in e:
        return "The configured Gemini model is not available to this API key."
    if any(s in e for s in ("UNAVAILABLE", "DEADLINE_EXCEEDED", "503", "504")):
        return "Gemini was overloaded or timed out, even after several retries."
    if "API key" in e or "api_key" in e or "GOOGLE_API_KEY" in e:
        return "No Gemini API key is configured on the server."
    return f"The Gemini call failed ({e[:120]})." if e else "The Gemini call failed."


def _best_identifier(loc: dict) -> tuple[str, str]:
    """(kind, text) of the strongest identifier at a label location: a serial or batch
    number proves the unit, a brand name only the product line."""
    order = ["serial_number", "batch_number", "barcode", "model_number", "label_text", "brand_name"]
    kinds = {c["kind"]: c["expected"] for c in loc.get("checks", [])}
    for i in loc.get("expected_kinds", []):
        kinds.setdefault(i["kind"], i["text"])
    for k in order:
        if k in kinds:
            return k.replace("_", " "), kinds[k]
    # results stored before kinds were recorded: prefer text that looks like a serial/batch number
    texts = loc.get("expected") or ["—"]
    numbered = [t for t in texts if any(w in t.lower() for w in ("batch", "serial", "s/n", "lot"))] or \
        [t for t in texts if sum(ch.isdigit() for ch in t) >= 6]
    return "label", (numbered or texts)[0]


def identity(ident: dict | None) -> dict | None:
    if not ident:
        return None
    if ident.get("error") or not ident.get("outcome"):
        return {"verdict": "Label check unavailable", "level": INFO, "detail": llm_error_text(ident.get("error"))}
    locs = ident.get("locations", [])
    loc = next((l for l in locs if l["status"] in ("missing", "mismatch")), None) or \
        next((l for l in locs if l["status"] in ("unit_match", "model_match")), None) or (locs[0] if locs else {})
    kind, expected = _best_identifier(loc) if loc else ("label", "—")
    where = loc.get("location", "the label")
    outcome = ident["outcome"]
    if outcome == "verified_unit":
        return {"verdict": "Label matches the delivered unit", "level": GOOD,
                "detail": f"Gemini read the label on the returned item ({where}). The {kind} “{expected}” matches the "
                          f"one recorded at delivery, which proves it is the same physical unit."}
    if outcome == "verified_model":
        return {"verdict": "Brand / model text matches", "level": OK,
                "detail": f"“{expected}” matches what was recorded at delivery, but there is no serial or batch number "
                          f"to prove it is the same unit, so this is only weak evidence."}
    if outcome == "label_missing":
        return {"verdict": "The label is missing", "level": BAD,
                "detail": f"At delivery there was a label ({where}) showing {kind} “{expected}”. Gemini looked at the "
                          f"same spot on the returned item and found no label at all."}
    if outcome == "mismatch":
        return {"verdict": "The label is different", "level": BAD,
                "detail": f"At delivery the {kind} was “{expected}”. On the returned item Gemini read "
                          f"“{loc.get('observed', '')[:80]}”, which does not match."}
    return {"verdict": "Label could not be read", "level": INFO,
            "detail": "The label area was not clear enough in the return photos to compare."}


WEAR = {
    "none": "No new wear or damage compared with the delivery photos.",
    "new_damage": "There is damage that is not in the delivery photos.",
    "less_wear_than_delivered": "It looks newer or less worn than the item that was delivered.",
    "different_wear_pattern": "Wear marks are in different places than on the delivered item.",
}
TAGS = {"intact": "Tags recorded at delivery are still attached.", "removed_or_cut": "Tags recorded at delivery are missing or cut.",
        "not_applicable": None}


def inspection(insp: dict | None) -> dict | None:
    if not insp:
        return None
    c = insp.get("confidence", 0)
    verdict, level = {
        "same_unit": (f"Same unit ({c}% confident)", GOOD),
        "different_unit": (f"Different unit ({c}% confident)", BAD),
        "inconclusive": ("Could not tell from the photos", INFO),
    }[insp["overall"]]
    bullets = [f"{f['view'].capitalize()}: {'; '.join(f['differences'])}" for f in insp.get("findings", []) if f.get("differences")]
    bullets.append(WEAR.get(insp.get("wear_change", "none"), ""))
    if insp.get("signs_of_use"):
        bullets.append("Signs of use: " + "; ".join(insp["signs_of_use"]))
    if TAGS.get(insp.get("tags_status")):
        bullets.append(TAGS[insp["tags_status"]])
    if insp.get("accessories_change"):
        bullets.append("Accessories: " + insp["accessories_change"])
    if insp.get("reason_consistency") == "inconsistent":
        bullets.append("The photos do not support the customer's stated return reason.")
    return {"verdict": verdict, "level": level, "detail": insp.get("evidence_summary", ""), "bullets": [b for b in bullets if b]}


def policy(p: dict | None) -> dict | None:
    if not p:
        return None
    cat = p["category"].replace("_", " & ")
    detail = f"Returned {p['days_since_delivery']} day(s) after delivery; {cat} items can be returned within {p['window_days']} days."
    if p.get("requires_functional_test"):
        detail += " Electronics also need a quick working test before restocking, because internal faults don't show in photos."
    if p["eligible"]:
        return {"value": f"day {p['days_since_delivery']} of {p['window_days']}", "verdict": "Within the return window", "level": GOOD, "detail": detail}
    return {"value": f"day {p['days_since_delivery']} of {p['window_days']}", "verdict": "Outside the return window", "level": BAD, "detail": detail}


def history(h: dict | None) -> dict | None:
    if not h:
        return None
    if h["tier"] == "new":
        return {"value": "first return", "verdict": "New customer: standard checks", "level": GOOD,
                "detail": "No earlier returns on record for this customer."}
    if h["tier"] == "regular":
        return {"value": f"{h['prior_returns']} earlier return(s)", "verdict": "Good history: standard checks", "level": GOOD,
                "detail": "None of this customer's earlier returns were flagged."}
    return {"value": f"{h['prior_flagged']} flagged return(s)", "verdict": "Stricter checks for this customer", "level": WARN,
            "detail": f"{h['prior_flagged']} of this customer's earlier returns were flagged, so a return is only "
                      f"auto-approved below risk {h['accept_below']} instead of {config.ACCEPT_BELOW}."}


def _effect(weight: float) -> str:
    if weight >= 2:
        return "strongly points to fraud"
    if weight >= 0.5:
        return "points to fraud"
    if weight <= -2:
        return "strongly points to a genuine return"
    if weight <= -0.5:
        return "points to a genuine return"
    return "neutral"


def _gemini_status(result: dict, order: dict) -> list[dict]:
    calls = {c["agent"]: c for c in result.get("llm_calls", [])}
    route = result.get("route", [])
    screen = result.get("screen") or {}
    decision = result.get("decision") or {}
    fp = (order or {}).get("fingerprint") or {}
    out = []

    # label check
    if "identity_verify" in calls:
        call = calls["identity_verify"]
        e = identity(result.get("identity")) if call["ok"] else {"verdict": "Unavailable", "level": INFO,
                                                                   "detail": llm_error_text(call.get("error"))}
        out.append({"agent": "Label check", "status": "ran" if call["ok"] else "unavailable", **e})
    else:
        if decision.get("basis") in ("policy", "capture_quality"):
            why = "The return was settled before any photo comparison (policy or photo quality)."
        elif not fp.get("identifiers"):
            why = "No printed label or serial number was recorded at delivery, so there was nothing to read."
        else:
            why = "The free visual check already showed a completely different product."
        out.append({"agent": "Label check", "status": "not_needed", "verdict": "Not needed", "level": INFO, "detail": why})

    # visual inspection
    second = result.get("second_opinion")
    if "visual_inspector" in calls:
        call = calls["visual_inspector"]
        e = inspection(result.get("inspection")) if call["ok"] else {"verdict": "Unavailable", "level": INFO,
                                                                       "detail": llm_error_text(call.get("error"))}
        out.append({"agent": "Visual inspection", "status": "ran" if call["ok"] else "unavailable", **e})
    else:
        if decision.get("basis") in ("policy", "capture_quality"):
            why = "Not needed: the return was settled by policy or photo quality."
        elif screen.get("verdict") == "clear_mismatch":
            why = "Not needed: the free visual check already showed a completely different product."
        elif "identity" in route:
            why = "Not needed: the label check and the visual check agreed, so a second Gemini call would add nothing."
        else:
            why = "Not needed: shape and colour matched strongly and there was no label to verify."
        out.append({"agent": "Visual inspection", "status": "not_needed", "verdict": "Not needed", "level": INFO,
                    "detail": why, "can_request": not (second and second.get("ok"))})
    if second:
        e = inspection(second.get("inspection")) if second.get("ok") else {"verdict": "Unavailable", "level": INFO,
                                                                             "detail": llm_error_text(second.get("error"))}
        out.append({"agent": "Second opinion (on request)", "status": "ran" if second.get("ok") else "unavailable",
                    "note": "Requested after the decision; shown for information and does not change it.", **e})
    return out


def explain_result(result: dict, order: dict) -> dict:
    d = result["decision"]
    checks = []
    for angle, q in (result.get("quality") or {}).items():
        if not q["ok"]:
            checks.append({"name": f"{angle.capitalize()} photo", "value": "unusable", "verdict": "Retake needed",
                           "level": WARN, "detail": q["problem"]})
    for name, e in (("Return window", policy(result.get("policy"))), ("Customer history", history(result.get("history")))):
        if e:
            checks.append({"name": name, **e})
    screen = result.get("screen")
    if screen:
        checks.append({"name": "Shape match", **shape(screen["shape_mean"])})
        checks.append({"name": "Colour match", **colour(screen["color_shift_median"])})
    for g in _gemini_status(result, order):
        if g["status"] == "ran" and g["agent"] != "Second opinion (on request)":
            checks.append({"name": g["agent"] + " (Gemini)", "value": "", "verdict": g["verdict"], "level": g["level"],
                           "detail": g["detail"]})

    sentence = {
        "ACCEPT": "Approve the refund: the returned item matches what was delivered.",
        "HUMAN_REVIEW": "A person should check this return before the refund is approved.",
        "REJECT": "Hold the refund: the returned item does not match what was delivered.",
        "RETAKE_REQUIRED": "The return photos can't be used. Retake them and submit again.",
    }[d["decision"]]
    if d.get("basis") == "policy":
        sentence = "Hold the refund: the return was requested after the return window closed."
    problems = [c for c in checks if c["level"] in (BAD, WARN)]
    reassurances = [c for c in checks if c["level"] in (GOOD, OK) and c["name"] not in ("Return window", "Customer history")]
    reasons = [f"{c['name']}: {c['verdict'].lower()}" for c in (problems if d["decision"] != "ACCEPT" else reassurances)[:3]]

    views = {}
    if screen:
        for a in config.ANGLES:
            s, c = shape(screen["shape"][a]), colour(screen["color_shift"][a])
            views[a] = {"shape": s["value"], "shape_verdict": s["verdict"], "shape_level": s["level"],
                        "colour_verdict": c["verdict"], "colour_level": c["level"]}

    evidence = [{**e, "effect": _effect(e["weight"])} for e in d.get("evidence", [])]
    return {"decision": {"sentence": sentence, "reasons": reasons, "risk_band": risk_band(d.get("risk_score"))},
            "checks": checks, "gemini": _gemini_status(result, order), "views": views, "evidence": evidence}
