"""Customer history agent: prior returns and flags for this customer drive
dynamic thresholds. A first-time returner gets the standard cut-offs; each prior
flagged return sends more borderline cases to a human."""
from returnguard import config, storage


def customer_profile(customer_id: str, exclude_return_id: int | None = None) -> dict:
    stats = storage.customer_return_stats(customer_id, exclude_return_id)
    flagged = stats["flagged"]
    if stats["returns"] == 0:
        tier = "new"
    elif flagged == 0:
        tier = "regular"
    else:
        tier = "repeat_flagged"
    shift = min(config.HISTORY_PENALTY_CAP, config.HISTORY_PENALTY_PER_FLAG * flagged)
    return {"customer_id": customer_id, "tier": tier, "prior_returns": stats["returns"], "prior_flagged": flagged,
            "accept_below": config.ACCEPT_BELOW - shift, "reject_from": config.REJECT_FROM}
