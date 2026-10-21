"""Policy agent: return window, category rules and reason eligibility (deterministic)."""
from datetime import datetime

from returnguard import config


def check_policy(category: str, delivered_at: datetime, requested_at: datetime, reason: str) -> dict:
    window = config.RETURN_WINDOW_DAYS.get(category, config.RETURN_WINDOW_DAYS["other"])
    days = max(0, (requested_at - delivered_at).days)
    eligible = days <= window
    notes = []
    if not eligible:
        notes.append(f"Requested {days} days after delivery; the {category} return window is {window} days.")
    if reason not in config.RETURN_REASONS:
        notes.append("Unknown return reason; treated as 'changed my mind'.")
    functional_test = category in config.FUNCTIONAL_TEST_CATEGORIES
    if functional_test:
        notes.append("Electronics: run a functional test before restocking; internal faults are not visible in photos.")
    return {"eligible": eligible, "category": category, "window_days": window, "days_since_delivery": days,
            "reason": reason if reason in config.RETURN_REASONS else "changed_mind",
            "requires_functional_test": functional_test, "notes": notes}
