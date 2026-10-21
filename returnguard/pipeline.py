"""The return-verification graph (LangGraph).

    intake ──► policy ─┐
           ├─► history ─┼─► triage ──► identity ──► inspector ──► decide
           └─► screen  ─┘     │            │                       ▲
                              └────────────┴───── (fast paths) ────┘

Local stages are free and run first; each LLM agent only runs when the cheaper
evidence before it can't settle the case. Every node is timed, and every LLM
call is recorded with its tokens, retries and latency.
"""
import operator
import time
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from returnguard import config, imaging, llm
from returnguard.agents import decision, history, identity, inspector, policy, screen
from returnguard.embeddings import ViewFeatures, view_features


class ReturnState(TypedDict, total=False):
    # inputs
    order: dict                 # delivery record: customer, category, delivered_at, fingerprint, features
    delivery_cutouts: dict      # angle -> RGBA cut-out saved at delivery (for the LLM agents)
    return_images: dict         # angle -> RGB photo
    reason: str
    requested_at: str
    return_id: int | None
    # produced by nodes
    return_cutouts: dict
    return_features: dict
    quality: dict
    policy: dict
    history: dict
    screen: dict
    identity: dict
    inspection: dict
    decision: dict
    trace: Annotated[list, operator.add]
    llm_calls: Annotated[list, operator.add]


def _timed(name, fn):
    def node(state):
        start = time.perf_counter()
        out = fn(state) or {}
        out["trace"] = [{"node": name, "ms": round((time.perf_counter() - start) * 1000)}]
        return out
    node.__name__ = name
    return node


# ── nodes ──────────────────────────────────────────────────────────────────
def intake(state):
    cutouts, feats, quality = {}, {}, {}
    for angle in config.ANGLES:
        img = state["return_images"][angle]
        cutouts[angle] = imaging.remove_background(img)
        quality[angle] = asdict(imaging.assess_quality(img, cutouts[angle]))
        feats[angle] = view_features(cutouts[angle])
    return {"return_cutouts": cutouts, "return_features": feats, "quality": quality}


def policy_node(state):
    order = state["order"]
    return {"policy": policy.check_policy(order["category"], datetime.fromisoformat(order["delivered_at"]),
                                          datetime.fromisoformat(state["requested_at"]), state["reason"])}


def history_node(state):
    return {"history": history.customer_profile(state["order"]["customer_id"], state.get("return_id"))}


def screen_node(state):
    delivered = {a: ViewFeatures.from_dict(f) for a, f in state["order"]["features"].items()}
    return {"screen": screen.visual_screen(delivered, state["return_features"])}


def identity_node(state):
    try:
        result, rec = identity.verify(state["order"]["fingerprint"], state["return_cutouts"])
        return {"identity": result, "llm_calls": [rec.to_dict()]}
    except llm.LLMError as err:
        return {"identity": {"outcome": None, "error": str(err)}, "llm_calls": [err.record.to_dict()]}


def inspector_node(state):
    order = state["order"]
    reason_text = config.RETURN_REASONS.get(state["reason"], state["reason"])
    try:
        result, rec = inspector.inspect(state["delivery_cutouts"], state["return_cutouts"], order.get("fingerprint"),
                                        order["category"], reason_text)
        return {"inspection": result.model_dump(), "llm_calls": [rec.to_dict()]}
    except llm.LLMError as err:
        return {"inspection": None, "llm_calls": [err.record.to_dict()]}


def decide_node(state):
    return {"decision": decision.decide(state)}


# ── routing ────────────────────────────────────────────────────────────────
def after_intake(state):
    if any(not q["ok"] for q in state["quality"].values()):
        return "decide"
    return ["policy", "history", "screen"]          # fan out: these three run in parallel


def after_triage(state):
    if not state["policy"]["eligible"]:
        return "decide"
    verdict = state["screen"]["verdict"]
    if verdict == "clear_mismatch":
        return "decide"                              # fast reject, no LLM
    fp = state["order"].get("fingerprint")
    if fp and fp.get("identifiers"):
        return "identity"                            # a label exists: read it before trusting looks
    if verdict == "strong_match" and not _needs_wear_check(state):
        return "decide"                              # fast accept, no LLM
    return "inspector"


def after_identity(state):
    outcome = state["identity"].get("outcome")
    strong = state["screen"]["verdict"] == "strong_match"
    if outcome in ("mismatch", "label_missing") and not strong:
        return "decide"                              # label and looks agree: swap
    if outcome in ("verified_unit", "verified_model") and strong and not _needs_wear_check(state):
        return "decide"                              # label and looks agree: same unit
    return "inspector"                               # conflict, unreadable, or wear check needed


def _needs_wear_check(state):
    """Worn-and-returned clothing is the same unit, so it looks like a perfect match."""
    return state["order"]["category"] in config.WEAR_CHECK_CATEGORIES


@lru_cache(maxsize=1)
def graph():
    g = StateGraph(ReturnState)
    for name, fn in [("intake", intake), ("policy", policy_node), ("history", history_node),
                     ("screen", screen_node), ("triage", lambda s: {}), ("identity", identity_node),
                     ("inspector", inspector_node), ("decide", decide_node)]:
        g.add_node(name, _timed(name, fn))
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", after_intake, ["policy", "history", "screen", "decide"])
    for name in ("policy", "history", "screen"):
        g.add_edge(name, "triage")
    g.add_conditional_edges("triage", after_triage, ["identity", "inspector", "decide"])
    g.add_conditional_edges("identity", after_identity, ["inspector", "decide"])
    g.add_edge("inspector", "decide")
    g.add_edge("decide", END)
    return g.compile()


def run(order: dict, delivery_cutouts: dict, return_images: dict, reason: str, requested_at: str | None = None,
        return_id: int | None = None, on_progress=None) -> tuple[dict, dict]:
    """Run the graph. Returns (JSON-safe result, raw final state).
    `on_progress(node_name)` is called as each node finishes (for live UI updates)."""
    inputs = {
        "order": order, "delivery_cutouts": delivery_cutouts, "return_images": return_images, "reason": reason,
        "requested_at": requested_at or datetime.now(timezone.utc).isoformat(), "return_id": return_id,
        "trace": [], "llm_calls": [],
    }
    state = None
    for mode, chunk in graph().stream(inputs, stream_mode=["updates", "values"]):
        if mode == "updates" and on_progress:
            for node in chunk:
                on_progress(node)
        elif mode == "values":
            state = chunk
    calls = state.get("llm_calls", [])
    result = {
        "decision": state["decision"],
        "quality": state.get("quality"),
        "policy": state.get("policy"),
        "history": state.get("history"),
        "screen": state.get("screen"),
        "identity": state.get("identity"),
        "inspection": state.get("inspection"),
        "route": [t["node"] for t in state["trace"]],
        "trace": state["trace"],
        "llm_calls": calls,
        "llm_call_count": len(calls),
        "llm_tokens": sum(c["input_tokens"] + c["output_tokens"] for c in calls),
    }
    return result, state
