"""Evaluate ReturnGuard on the paired dataset (Dataset/pairs.csv).

Positive class = fraud (the returned item is not the delivered unit).
A return counts as *flagged* when the pipeline does not auto-accept it
(HUMAN_REVIEW or REJECT): the refund does not go out automatically.

Reports detection metrics (precision, recall, F1, F0.5), ablations (the original
v1 embedding gate, local evidence only, full multi-agent pipeline) and agentic
metrics (LLM calls per return, schema validity, retries, per-agent accuracy,
tokens, cost, latency). Results go to results/eval_results.json, which the
website reads, plus a Markdown report and a per-pair CSV.

    python scripts/evaluate.py                 # cached LLM answers are reused
    python scripts/evaluate.py --fresh         # ignore the LLM cache
    python scripts/evaluate.py --model gemini-3.5-flash
"""
import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--model", help="Gemini model for all agents (default: config.LLM_MODEL)")
parser.add_argument("--fresh", action="store_true", help="do not reuse cached LLM answers")
parser.add_argument("--limit", type=int, help="only the first N pairs (smoke test)")
parser.add_argument("--exclude-items", default="", help="comma-separated items to leave out, e.g. headphones_blue,headphones_black")
parser.add_argument("--no-baseline", action="store_true", help="skip the v1 baseline")
parser.add_argument("--out", default=str(ROOT / "results"), help="output folder")
args = parser.parse_args()

os.environ["RG_LLM_CACHE"] = "0" if args.fresh else "1"
os.environ["RG_DATA_DIR"] = str(ROOT / ".cache" / "eval_data")   # empty history: every customer is new
if args.model:
    os.environ["RG_LLM_MODEL"] = args.model

from returnguard import config, imaging, llm, pipeline  # noqa: E402  (env must be set first)
from returnguard.agents import decision, identity  # noqa: E402
from returnguard.embeddings import view_features  # noqa: E402

DATASET = ROOT / "Dataset"
CATEGORY = {"speaker": "electronics", "headphones": "electronics", "shaker": "home_kitchen", "bottle": "home_kitchen"}
# Added to the dataset after thresholds and evidence weights were frozen on the first 6 items
HELD_OUT_ITEMS = ["headphones_blue", "headphones_black"]
# USD per 1M tokens (input, output incl. thinking), Gemini API paid-tier list prices
PRICES = {"gemini-2.5-flash": (0.30, 2.50)}


def safe_div(a, b):
    return a / b if b else 0.0


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    """95% Wilson score interval for a proportion k/n. With few samples, a 100% is
    really '100% with a lower bound well below it', and the interval says how far."""
    if n == 0:
        return [0.0, 0.0]
    p, d = k / n, 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def binary_metrics(y_true: list[bool], y_pred: list[bool]) -> dict:
    tp = sum(t and p for t, p in zip(y_true, y_pred))
    fp = sum(not t and p for t, p in zip(y_true, y_pred))
    fn = sum(t and not p for t, p in zip(y_true, y_pred))
    tn = sum(not t and not p for t, p in zip(y_true, y_pred))
    precision, recall = safe_div(tp, tp + fp), safe_div(tp, tp + fn)

    def f_beta(beta):
        b2 = beta * beta
        return safe_div((1 + b2) * precision * recall, b2 * precision + recall)

    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f_beta(1), 4), "f0_5": round(f_beta(0.5), 4), "accuracy": round(safe_div(tp + tn, len(y_true)), 4),
            "false_rejection_rate": round(safe_div(fp, fp + tn), 4),
            "precision_ci": wilson(tp, tp + fp), "recall_ci": wilson(tp, tp + fn),
            "false_rejection_rate_ci": wilson(fp, fp + tn)}


def auc(scores_pos: list[float], scores_neg: list[float]) -> float:
    """ROC AUC: probability a fraud pair scores *lower* similarity than a genuine one."""
    wins = sum((p < n) + 0.5 * (p == n) for p in scores_pos for n in scores_neg)
    return round(safe_div(wins, len(scores_pos) * len(scores_neg)), 4)


def ensure_dataset():
    if not (DATASET / "pairs.csv").exists() or not (DATASET / "same").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_dataset.py")], check=True)


def load_views(label, phase, pair_id):
    return {a: imaging.load_image(DATASET / label / phase / a / f"{pair_id}.jpeg") for a in config.ANGLES}


# ── v1 baseline: the original embedding gate, re-implemented faithfully ────
def v1_baseline(rows) -> list[float]:
    """Original method: pad cut-out with black to a square, resize 448, DINOv2 via the
    HF pipeline (resize 256 + centre crop 224), mean of ALL patch tokens (padding
    included), cosine per view, weighted by silhouette-Laplacian 'sharpness'."""
    import numpy as np
    import torch
    from PIL import Image
    from transformers import pipeline as hf_pipeline

    extractor = hf_pipeline(model="facebook/dinov2-base", task="image-feature-extraction")
    cache = {}

    def feats(img):
        key = imaging.image_digest(img)
        if key not in cache:
            cut = imaging.remove_background(img)
            rgb = cut.convert("RGB")
            side = max(rgb.size)
            sq = Image.new("RGB", (side, side), (0, 0, 0))
            sq.paste(rgb, ((side - rgb.width) // 2, (side - rgb.height) // 2))
            emb = torch.tensor(extractor(sq.resize((448, 448), Image.LANCZOS))[0])[1:].mean(0)
            arr = np.array(cut.convert("L"), dtype=np.float32)
            lap = np.roll(arr, -1, 0) + np.roll(arr, 1, 0) + np.roll(arr, -1, 1) + np.roll(arr, 1, 1) - 4 * arr
            cache[key] = (emb, max(float(lap.var()), 1.0))
        return cache[key]

    scores = []
    for r in rows:
        d, rt = load_views(r["label"], "delivery_images", r["pair_id"]), load_views(r["label"], "return_images", r["pair_id"])
        sims, qs = [], []
        for a in config.ANGLES:
            (e1, _), (e2, q) = feats(d[a]), feats(rt[a])
            sims.append(torch.nn.functional.cosine_similarity(e1, e2, dim=0).item())
            qs.append(q)
        scores.append(sum(s * q for s, q in zip(sims, qs)) / sum(qs))
    return scores


def main():
    ensure_dataset()
    rows = list(csv.DictReader(open(DATASET / "pairs.csv")))
    excluded = {s.strip() for s in args.exclude_items.split(",") if s.strip()}
    if excluded:
        rows = [r for r in rows if r["delivery_item"] not in excluded and r["return_item"] not in excluded]
    if args.limit:
        rows = rows[:args.limit]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    model = config.LLM_MODEL
    print(f"Evaluating {len(rows)} pairs with {model} (LLM cache {'off' if args.fresh else 'on'})")

    now = datetime.now(timezone.utc)
    deliveries = {}   # delivery photos -> (order, cutouts); the same delivery recurs across many pairs
    delivery_calls = []
    per_pair = []
    t_start = time.time()

    for i, r in enumerate(rows, 1):
        item = r["delivery_item"]
        imgs = load_views(r["label"], "delivery_images", r["pair_id"])
        key = tuple(imaging.image_digest(imgs[a]) for a in config.ANGLES)
        if key not in deliveries:
            cutouts = {a: imaging.remove_background(imgs[a]) for a in config.ANGLES}
            try:
                fp, rec = identity.fingerprint(cutouts)
                fingerprint = fp.model_dump()
            except llm.LLMError as err:
                fingerprint, rec = None, err.record
            delivery_calls.append(rec.to_dict())
            order = {"order_id": f"eval-{item}", "customer_id": "eval-customer", "category": CATEGORY[item.split('_')[0]],
                     "delivered_at": (now - timedelta(days=1)).isoformat(), "fingerprint": fingerprint,
                     "features": {a: view_features(cutouts[a]).to_dict() for a in config.ANGLES}}
            deliveries[key] = (order, cutouts)
        order, cutouts = deliveries[key]

        result, state = pipeline.run(order, cutouts, load_views(r["label"], "return_images", r["pair_id"]),
                                     reason="changed_mind", requested_at=now.isoformat())
        local_only = decision.decide({**state, "identity": None, "inspection": None, "llm_calls": []})
        d = result["decision"]
        llm_ms = sum(c["latency_s"] for c in result["llm_calls"]) * 1000
        local_ms = sum(t["ms"] for t in result["trace"] if t["node"] not in ("identity", "inspector"))
        per_pair.append({
            "label": r["label"], "pair_id": int(r["pair_id"]), "delivery_item": item, "return_item": r["return_item"],
            "pair_type": r["pair_type"], "is_fraud": r["label"] == "different",
            "decision": d["decision"], "risk_score": d["risk_score"], "fraud_type": d.get("fraud_type"),
            "local_only_decision": local_only["decision"],
            "route": result["route"], "llm_calls": result["llm_calls"], "llm_call_count": result["llm_call_count"],
            "screen_verdict": result["screen"]["verdict"] if result["screen"] else None,
            "shape_mean": result["screen"]["shape_mean"] if result["screen"] else None,
            "color_shift": result["screen"]["color_shift_median"] if result["screen"] else None,
            "identity_outcome": (result["identity"] or {}).get("outcome"),
            "inspector_overall": (result["inspection"] or {}).get("overall"),
            "inspector_confidence": (result["inspection"] or {}).get("confidence"),
            "evidence": d["evidence"], "latency_ms_est": round(local_ms + llm_ms),
        })
        p = per_pair[-1]
        mark = "OK " if (p["decision"] != "ACCEPT") == p["is_fraud"] else "ERR"
        print(f"[{i:2d}/{len(rows)}] {mark} {r['label']:9s} {r['pair_id']:>2} {item:9s}->{r['return_item']:9s} "
              f"{p['decision']:12s} risk {str(p['risk_score']):>3}  llm {p['llm_call_count']}  "
              f"route {'>'.join(n for n in p['route'] if n not in ('policy', 'history', 'screen', 'triage'))}", flush=True)

    # An LLM outage turns decisions into fail-safe reviews: those numbers measure the outage,
    # not the system, so never publish them. Successful answers stay cached for the next run.
    failed = [c for p in per_pair for c in p["llm_calls"] if not c["ok"]] + [c for c in delivery_calls if not c["ok"]]
    if failed:
        partial = out_dir / "eval_results.partial.json"
        partial.write_text(json.dumps({"failed_calls": failed, "per_pair": per_pair}, indent=2, default=str), encoding="utf-8")
        print(f"\n{len(failed)} LLM call(s) failed (e.g. {failed[0]['error'][:120]}).\n"
              f"Published results were NOT updated. Re-run when the quota resets; cached answers are reused. "
              f"Details: {partial}")
        sys.exit(1)

    # ── detection metrics ──────────────────────────────────────────────────
    y = [p["is_fraud"] for p in per_pair]
    full = binary_metrics(y, [p["decision"] != "ACCEPT" for p in per_pair])
    local = binary_metrics(y, [p["local_only_decision"] != "ACCEPT" for p in per_pair])
    auto_reject = binary_metrics(y, [p["decision"] == "REJECT" for p in per_pair])
    # items added after every threshold and weight was frozen: the closest thing to a held-out test
    held = [p for p in per_pair if {p["delivery_item"], p["return_item"]} & set(HELD_OUT_ITEMS)]
    held_out = {"items": HELD_OUT_ITEMS, "pairs": len(held), "genuine": sum(not p["is_fraud"] for p in held),
                "fraud": sum(p["is_fraud"] for p in held),
                **binary_metrics([p["is_fraud"] for p in held], [p["decision"] != "ACCEPT" for p in held])} if held else None
    confusion = {lab: Counter(p["decision"] for p in per_pair if p["is_fraud"] == (lab == "fraud"))
                 for lab in ("genuine", "fraud")}
    by_type = defaultdict(Counter)
    for p in per_pair:
        by_type[p["pair_type"]][p["decision"]] += 1

    ablations = []
    shape_auc = auc([p["shape_mean"] for p in per_pair if p["is_fraud"] and p["shape_mean"] is not None],
                    [p["shape_mean"] for p in per_pair if not p["is_fraud"] and p["shape_mean"] is not None])
    if not args.no_baseline:
        print("Computing v1 baseline (original embedding gate)...", flush=True)
        v1 = v1_baseline(rows)
        for p, s in zip(per_pair, v1):
            p["v1_score"] = round(s, 4)
        v1_metrics = binary_metrics(y, [s <= 0.94 for s in v1])
        ablations.append({"name": "v1: original embedding gate", "detail": "patch-mean incl. padding, flag if <= 0.94",
                          "llm_calls_per_return": None, "auc": auc([s for s, t in zip(v1, y) if t], [s for s, t in zip(v1, y) if not t]),
                          **v1_metrics})
    ablations.append({"name": "v2: local evidence only", "detail": "object-only DINOv2 + colour, no LLM",
                      "llm_calls_per_return": 0, "auc": shape_auc, **local})
    calls_per_return = statistics.mean(p["llm_call_count"] for p in per_pair)
    ablations.append({"name": "v2: full multi-agent pipeline", "detail": "screen + identity agent + inspector + decision",
                      "llm_calls_per_return": round(calls_per_return, 2), "auc": None, **full})

    # ── agentic metrics ────────────────────────────────────────────────────
    all_calls = [c for p in per_pair for c in p["llm_calls"]] + delivery_calls
    by_agent = defaultdict(list)
    for c in all_calls:
        by_agent[c["agent"]].append(c)
    ident_runs = [p for p in per_pair if p["identity_outcome"]]
    insp_runs = [p for p in per_pair if p["inspector_overall"]]
    ident_ok = sum((p["identity_outcome"] in ("mismatch", "label_missing")) == p["is_fraud"] for p in ident_runs)
    insp_ok = sum((p["inspector_overall"] == "different_unit") == p["is_fraud"] for p in insp_runs)
    tokens_in = sum(c["input_tokens"] for p in per_pair for c in p["llm_calls"])
    tokens_out = sum(c["output_tokens"] for p in per_pair for c in p["llm_calls"])
    price = PRICES.get(model)
    cost_per_1k = round((tokens_in * price[0] + tokens_out * price[1]) / 1e6 / len(per_pair) * 1000, 2) if price else None
    route_counts = Counter(" > ".join(n for n in p["route"] if n not in ("policy", "history", "screen", "triage"))
                           for p in per_pair)
    agentic = {
        "llm_calls_per_return": round(calls_per_return, 2),
        "v1_llm_calls_per_return_upper_bound": 4,
        "decided_without_llm_pct": round(100 * safe_div(sum(p["llm_call_count"] == 0 for p in per_pair), len(per_pair)), 1),
        "llm_call_distribution": dict(sorted(Counter(p["llm_call_count"] for p in per_pair).items())),
        "schema_valid_first_try_pct": round(100 * safe_div(sum(c["ok"] and c["attempts"] == 1 for c in all_calls), len(all_calls)), 1),
        "schema_valid_after_retries_pct": round(100 * safe_div(sum(c["ok"] for c in all_calls), len(all_calls)), 1),
        "total_retries": sum(max(0, c["attempts"] - 1) for c in all_calls),
        "agents": {name: {"calls": len(cs), "mean_latency_s": round(statistics.mean(c["latency_s"] for c in cs), 1),
                          "mean_tokens": round(statistics.mean(c["input_tokens"] + c["output_tokens"] for c in cs))}
                   for name, cs in by_agent.items()},
        "identity_agent_accuracy": {"runs": len(ident_runs), "correct": ident_ok},
        "inspector_accuracy": {"runs": len(insp_runs), "correct": insp_ok},
        "tokens_per_return": round((tokens_in + tokens_out) / len(per_pair)),
        "est_cost_usd_per_1000_returns": cost_per_1k,
        "latency_s_per_return": {"mean": round(statistics.mean(p["latency_ms_est"] for p in per_pair) / 1000, 1),
                                 "p_max": round(max(p["latency_ms_est"] for p in per_pair) / 1000, 1)},
        "routes": dict(route_counts.most_common()),
    }

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model, "embedding_model": config.EMBED_MODEL, "background_model": config.BG_MODEL,
        "positive_class": "fraud (returned item is not the delivered unit)",
        "flagged_means": "HUMAN_REVIEW or REJECT (refund not auto-approved)",
        "dataset": {"pairs": len(per_pair), "genuine": y.count(False), "fraud": y.count(True),
                    "items": len({p["delivery_item"] for p in per_pair}),
                    "pair_types": dict(Counter(p["pair_type"] for p in per_pair)),
                    "note": f"{len({p['delivery_item'] for p in per_pair})} physical items. Genuine returns are simulated "
                            f"re-captures (the delivery photo, edited) except "
                            f"{sum(p['pair_type'] == 'same_item_real_recapture' for p in per_pair)} real re-photographs "
                            f"from a separate photo session."},
        "thresholds": {"fast_reject_shape": config.FAST_REJECT_SHAPE, "fast_accept_shape": config.FAST_ACCEPT_SHAPE,
                       "fast_accept_min_view": config.FAST_ACCEPT_MIN_VIEW,
                       "fast_accept_max_color_shift": config.FAST_ACCEPT_MAX_COLOR_SHIFT,
                       "accept_below": config.ACCEPT_BELOW, "reject_from": config.REJECT_FROM},
        "real_recapture": [
            {"kind": label, "pairs": len(ps), "accepted": sum(p["decision"] == "ACCEPT" for p in ps),
             "flagged": sum(p["decision"] != "ACCEPT" for p in ps)}
            for kind, label in (("same_item_recapture", "Simulated re-capture (same photo, edited)"),
                                ("same_item_real_recapture", "Real re-photograph (separate photo session)"))
            if (ps := [p for p in per_pair if p["pair_type"] == kind])],
        "retakes": {"count": sum(p["decision"] == "RETAKE_REQUIRED" for p in per_pair),
                    "note": "Photo rejected by the quality gate; counted as flagged (conservative: it can only lower precision)."},
        "metrics": full, "held_out": held_out, "auto_reject_metrics": auto_reject,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "by_pair_type": {k: dict(v) for k, v in by_type.items()},
        "ablations": ablations, "agentic": agentic,
        "runtime_s": round(time.time() - t_start),
        "per_pair": per_pair,
    }
    (out_dir / "eval_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    write_markdown(results, out_dir / "eval_report.md")
    with open(out_dir / "eval_pairs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "pair_id", "delivery_item", "return_item", "pair_type", "decision", "risk_score",
                    "llm_calls", "shape_mean", "color_shift", "identity", "inspector", "v1_score"])
        for p in per_pair:
            w.writerow([p["label"], p["pair_id"], p["delivery_item"], p["return_item"], p["pair_type"], p["decision"],
                        p["risk_score"], p["llm_call_count"], p["shape_mean"], p["color_shift"], p["identity_outcome"],
                        p["inspector_overall"], p.get("v1_score")])

    m = full
    print(f"\nFull pipeline: precision {m['precision']:.3f}  recall {m['recall']:.3f}  F1 {m['f1']:.3f}  "
          f"F0.5 {m['f0_5']:.3f}  (TP {m['tp']} FP {m['fp']} FN {m['fn']} TN {m['tn']})")
    print(f"LLM calls/return {agentic['llm_calls_per_return']}, decided without LLM {agentic['decided_without_llm_pct']}%")
    for a in ablations:
        print(f"  {a['name']:32s} P {a['precision']:.3f} R {a['recall']:.3f} F0.5 {a['f0_5']:.3f}")
    print(f"Wrote {out_dir / 'eval_results.json'}")


def pct(x):
    return f"{100 * x:.1f}%"


def write_markdown(r, path):
    m, a = r["metrics"], r["agentic"]
    lines = [
        "# ReturnGuard evaluation", "",
        f"Generated {r['generated_at']} with `{r['model']}`. Dataset: {r['dataset']['pairs']} pairs "
        f"({r['dataset']['genuine']} genuine, {r['dataset']['fraud']} fraud) from {r['dataset']['items']} items. "
        f"{r['dataset']['note']}", "",
        "Positive class = fraud. *Flagged* = not auto-accepted (human review or reject).", "",
        "| Metric | Value | 95% interval |", "|---|---|---|",
        f"| Precision | {pct(m['precision'])} ({m['tp']}/{m['tp'] + m['fp']}) | {pct(m['precision_ci'][0])} – {pct(m['precision_ci'][1])} |",
        f"| Recall | {pct(m['recall'])} ({m['tp']}/{m['tp'] + m['fn']}) | {pct(m['recall_ci'][0])} – {pct(m['recall_ci'][1])} |",
        f"| F1 | {pct(m['f1'])} | |", f"| **F0.5** | **{pct(m['f0_5'])}** | |",
        f"| False rejection rate (genuine returns flagged) | {pct(m['false_rejection_rate'])} ({m['fp']}/{m['fp'] + m['tn']}) | "
        f"{pct(m['false_rejection_rate_ci'][0])} – {pct(m['false_rejection_rate_ci'][1])} |",
        f"| Confusion (TP / FP / FN / TN) | {m['tp']} / {m['fp']} / {m['fn']} / {m['tn']} | |",
        f"| Retake requests (counted as flagged) | {r['retakes']['count']} | |", "",
        "Intervals are 95% Wilson score intervals: with this few pairs, a perfect score still has a wide range.", "",
    ]
    h = r.get("held_out")
    if h:
        lines += [
            f"## Held-out items ({', '.join(h['items'])})", "",
            "Added after every threshold and evidence weight was frozen on the first 6 items, and photographed in real, "
            "cluttered scenes (on laptops, held in hand). The closest thing to an unseen test set here.", "",
            "| Metric | Value | 95% interval |", "|---|---|---|",
            f"| Pairs | {h['pairs']} ({h['genuine']} genuine, {h['fraud']} fraud) | |",
            f"| Precision | {pct(h['precision'])} ({h['tp']}/{h['tp'] + h['fp']}) | {pct(h['precision_ci'][0])} – {pct(h['precision_ci'][1])} |",
            f"| Recall | {pct(h['recall'])} ({h['tp']}/{h['tp'] + h['fn']}) | {pct(h['recall_ci'][0])} – {pct(h['recall_ci'][1])} |",
            f"| F0.5 | {pct(h['f0_5'])} | |",
            f"| Genuine returns flagged | {pct(h['false_rejection_rate'])} ({h['fp']}/{h['fp'] + h['tn']}) | |", "",
        ]
    lines += [
        "## Ablations", "", "| System | LLM calls / return | Precision | Recall | F0.5 | AUC |", "|---|---|---|---|---|---|",
    ]
    for ab in r["ablations"]:
        calls = "–" if ab["llm_calls_per_return"] is None else ab["llm_calls_per_return"]
        lines.append(f"| {ab['name']} | {calls} | {pct(ab['precision'])} | {pct(ab['recall'])} | {pct(ab['f0_5'])} | "
                     f"{ab['auc'] if ab['auc'] is not None else '–'} |")
    lines += ["", "## Decisions by pair type", "", "| Pair type | ACCEPT | HUMAN_REVIEW | REJECT | RETAKE |", "|---|---|---|---|---|"]
    for k, v in r["by_pair_type"].items():
        lines.append(f"| {k} | {v.get('ACCEPT', 0)} | {v.get('HUMAN_REVIEW', 0)} | {v.get('REJECT', 0)} | "
                     f"{v.get('RETAKE_REQUIRED', 0)} |")
    lines += ["", "## Agentic metrics", "",
              f"- LLM calls per return: **{a['llm_calls_per_return']}** (v1 made up to {a['v1_llm_calls_per_return_upper_bound']})",
              f"- Decided with no LLM call: **{a['decided_without_llm_pct']}%**",
              f"- Structured output valid on first try: {a['schema_valid_first_try_pct']}% "
              f"(after retries: {a['schema_valid_after_retries_pct']}%), retries: {a['total_retries']}",
              f"- Identity agent correct: {a['identity_agent_accuracy']['correct']}/{a['identity_agent_accuracy']['runs']}",
              f"- Visual inspector correct: {a['inspector_accuracy']['correct']}/{a['inspector_accuracy']['runs']}",
              f"- Tokens per return: {a['tokens_per_return']}; est. cost per 1,000 returns: "
              f"{'$' + str(a['est_cost_usd_per_1000_returns']) if a['est_cost_usd_per_1000_returns'] is not None else 'n/a'}",
              f"- Latency per return: mean {a['latency_s_per_return']['mean']} s, max {a['latency_s_per_return']['p_max']} s",
              "", "Routes taken:", ""]
    lines += [f"- `{k or 'intake only'}`: {v}" for k, v in a["routes"].items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
