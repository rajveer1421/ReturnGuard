"""Application services behind the web API: customer accounts, delivery registration
(the order is created at delivery time), asynchronous return processing with an audit
trail, and an on-demand Gemini second opinion."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from PIL import Image, UnidentifiedImageError

from returnguard import config, imaging, llm, pipeline, storage
from returnguard.agents import identity, inspector
from returnguard.embeddings import view_features
from returnguard.explain import llm_error_text

log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="return-pipeline")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class InputError(ValueError):
    """Bad request data; the message is safe to show to the user."""


class ForbiddenError(InputError):
    """The signed-in customer may not act on this resource."""


# ── customer accounts ──────────────────────────────────────────────────────
def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise InputError("Enter a valid email address.")
    return email


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10:
        raise InputError("Enter a 10-digit mobile number.")
    return digits


def sign_up(email: str, phone: str) -> dict:
    email, phone = normalize_email(email), normalize_phone(phone)
    if storage.find_customer_by_email(email):
        raise InputError("An account with this email already exists. Sign in instead.")
    return storage.create_customer(email, phone)


def sign_in(email: str, phone: str) -> dict:
    email, phone = normalize_email(email), normalize_phone(phone)
    customer = storage.find_customer_by_email(email)
    if customer is None or customer["phone"] != phone:
        raise InputError("No account matches this email and phone number.")
    return customer


def public_customer(c: dict) -> dict:
    return {"customer_id": c["customer_id"], "email": c["email"], "phone": "••••••" + c["phone"][-4:],
            "created_at": c["created_at"]}


# ── images on disk ─────────────────────────────────────────────────────────
def _load_all(files: dict) -> dict:
    images = {}
    for angle in config.ANGLES:
        data = files.get(angle)
        if not data:
            raise InputError("All three photos (front, back, side) are required.")
        try:
            images[angle] = imaging.load_image(data)
        except (UnidentifiedImageError, OSError):
            raise InputError(f"The {angle} upload is not a readable image.")
    return images


def order_dir(order_id: int):
    return config.IMAGE_DIR / "orders" / str(order_id)


def return_dir(order_id: int, return_id: int):
    """Return photos live inside their order: data/images/orders/<order_id>/returns/<return_id>/."""
    return order_dir(order_id) / "returns" / str(return_id)


def _save(images: dict, cutouts: dict, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for angle in config.ANGLES:
        images[angle].save(folder / f"{angle}.jpg", "JPEG", quality=90)
        cutouts[angle].save(folder / f"{angle}_cutout.png")


# ── delivery ───────────────────────────────────────────────────────────────
def register_delivery(files: dict, customer_id: str, product_name: str, category: str,
                      delivered_days_ago: int = 0) -> dict:
    if category not in config.RETURN_WINDOW_DAYS:
        raise InputError(f"Unknown category '{category}'.")
    images = _load_all(files)
    cutouts = {a: imaging.remove_background(images[a]) for a in config.ANGLES}
    quality = {a: imaging.assess_quality(images[a], cutouts[a]) for a in config.ANGLES}
    bad = [f"{a.capitalize()}: {q.problem}" for a, q in quality.items() if not q.ok]
    if bad:
        raise InputError(" ".join(bad))

    features = {a: view_features(cutouts[a]).to_dict() for a in config.ANGLES}
    delivered_at = (datetime.now(timezone.utc) - timedelta(days=max(0, delivered_days_ago))).isoformat(timespec="seconds")
    order_id = storage.create_order(customer_id, product_name, category, delivered_at, features)
    _save(images, cutouts, order_dir(order_id))

    try:
        fp, rec = identity.fingerprint(cutouts)
        fingerprint = fp.model_dump()
    except llm.LLMError as err:
        log.warning("fingerprint unavailable for order %s: %s", order_id, err)
        fingerprint, rec = None, err.record
    storage.set_fingerprint(order_id, fingerprint)
    storage.add_audit(order_id, None, "delivery_registered", {
        "quality": {a: q.__dict__ for a, q in quality.items()}, "fingerprint": fingerprint, "llm_call": rec.to_dict()})
    order = storage.get_order(order_id, with_features=False)
    order["fingerprint_error"] = None if fingerprint else llm_error_text(rec.error)
    return order


# ── return ─────────────────────────────────────────────────────────────────
def start_return(order_id: int, files: dict, reason: str, customer_id: str) -> int:
    order = storage.get_order(order_id)
    if order is None:
        raise InputError(f"Order #{order_id} does not exist. Register the delivery first.")
    if order["customer_id"] != customer_id:
        raise ForbiddenError(f"Order #{order_id} belongs to another customer. Sign in with that account to return it.")
    if reason not in config.RETURN_REASONS:
        raise InputError("Choose a return reason from the list.")
    images = _load_all(files)
    return_id = storage.create_return(order_id, reason)
    folder = return_dir(order_id, return_id)
    folder.mkdir(parents=True, exist_ok=True)
    for angle, img in images.items():
        img.save(folder / f"{angle}.jpg", "JPEG", quality=90)
    _executor.submit(_process_return, return_id, order, images, reason)
    return return_id


def _delivery_cutouts(order_id: int) -> dict:
    return {a: Image.open(order_dir(order_id) / f"{a}_cutout.png").convert("RGBA") for a in config.ANGLES}


def _process_return(return_id: int, order: dict, images: dict, reason: str):
    try:
        result, state = pipeline.run(order, _delivery_cutouts(order["order_id"]), images, reason, return_id=return_id,
                                     on_progress=lambda node: storage.add_progress(return_id, node))
        folder = return_dir(order["order_id"], return_id)
        for angle, cut in state["return_cutouts"].items():
            cut.save(folder / f"{angle}_cutout.png")
        for stage in ("quality", "policy", "history", "screen", "identity", "inspection", "decision"):
            if result.get(stage) is not None:
                storage.add_audit(order["order_id"], return_id, stage, result[stage])
        storage.add_audit(order["order_id"], return_id, "llm_calls", {"calls": result["llm_calls"]})
        d = result["decision"]
        storage.finish_return(return_id, d["decision"], d["risk_score"], result)
    except Exception as err:  # never leave a return stuck in PROCESSING
        log.exception("return %s failed", return_id)
        storage.finish_return(return_id, "ERROR", None, None, error=f"{type(err).__name__}: {err}")


def second_opinion(return_id: int, customer_id: str) -> dict:
    """Run the visual inspector on a finished return that didn't need it. Informational:
    the original decision and its audit trail stay unchanged."""
    ret = storage.get_return(return_id)
    if ret is None or not ret["result"]:
        raise InputError("This return has not finished processing yet.")
    if ret["customer_id"] != customer_id:
        raise ForbiddenError("This return belongs to another customer.")
    folder = return_dir(ret["order_id"], return_id)
    if not (folder / "front_cutout.png").exists():
        raise InputError("The return photos for this return are not available.")
    order = storage.get_order(ret["order_id"], with_features=False)
    returned = {a: Image.open(folder / f"{a}_cutout.png").convert("RGBA") for a in config.ANGLES}
    reason_text = config.RETURN_REASONS.get(ret["reason"], ret["reason"])
    try:
        insp, rec = inspector.inspect(_delivery_cutouts(ret["order_id"]), returned, order.get("fingerprint"),
                                      order["category"], reason_text)
        opinion = {"ok": True, "inspection": insp.model_dump(), "call": rec.to_dict()}
    except llm.LLMError as err:
        opinion = {"ok": False, "error": err.record.error, "call": err.record.to_dict()}
    result = ret["result"]
    result["second_opinion"] = opinion
    storage.update_result(return_id, result)
    storage.add_audit(ret["order_id"], return_id, "second_opinion", opinion)
    return opinion
