"""ReturnGuard web app: REST API + single-page UI.

    python app.py            # http://127.0.0.1:5000
"""
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import Flask, abort, jsonify, render_template, request, send_from_directory, session
from itsdangerous import BadSignature, URLSafeTimedSerializer

from returnguard import config, explain, service, storage
from returnguard.agents.history import customer_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _secret_key() -> str:
    """Session signing key: from RG_SECRET_KEY, else generated once and kept in data/ (git-ignored)."""
    if os.getenv("RG_SECRET_KEY"):
        return os.environ["RG_SECRET_KEY"]
    path = config.DATA_DIR / "secret_key"
    if not path.exists():
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = (config.MAX_UPLOAD_MB * 3 + 1) * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if os.getenv("SPACE_ID") or os.getenv("RG_CROSS_SITE_COOKIES") == "1":
    # On Hugging Face the app is shown in an iframe on huggingface.co, a different site: a Lax cookie is never sent
    # there, so sign-in would silently not stick. Allow it cross-site, HTTPS only, partitioned to that embedding.
    app.config.update(SESSION_COOKIE_SAMESITE="None", SESSION_COOKIE_SECURE=True, SESSION_COOKIE_PARTITIONED=True)
app.secret_key = _secret_key()
storage.init_db()

MEDIA_FILES = {f"{a}{suffix}" for a in config.ANGLES for suffix in (".jpg", "_cutout.png")}


def uploaded_images() -> dict:
    files = {}
    for angle in config.ANGLES:
        f = request.files.get(f"{angle}_image")
        files[angle] = f.read() if f else None
    return files


def media_urls(kind: str, item_id: int, token: str | None = None) -> dict:
    q = f"?t={token}" if token else ""
    return {a: {"photo": f"/media/{kind}/{item_id}/{a}.jpg{q}", "cutout": f"/media/{kind}/{item_id}/{a}_cutout.png{q}"}
            for a in config.ANGLES}


# The evidence report opens in a new tab. On Hugging Face the app itself runs inside an iframe, and its session cookie
# belongs to that embedding, so a new tab arrives signed out. The report link therefore carries a signed token that
# names the owner; it expires after REPORT_LINK_MAX_AGE_S and still only opens that customer's own data.
REPORT_LINK_MAX_AGE_S = 24 * 3600
_links = URLSafeTimedSerializer(app.secret_key, salt="report-link")


def report_token(customer_id: str) -> str:
    return _links.dumps(customer_id)


def viewer_id() -> str | None:
    """The signed-in customer, or the owner named by a valid report-link token."""
    customer = current_customer()
    if customer:
        return customer["customer_id"]
    token = request.args.get("t")
    if token:
        try:
            return _links.loads(token, max_age=REPORT_LINK_MAX_AGE_S)
        except BadSignature:
            return None
    return None


def current_customer() -> dict | None:
    cid = session.get("customer_id")
    return storage.get_customer(cid) if cid else None


def require_customer() -> dict:
    customer = current_customer()
    if customer is None:
        raise service.InputError("Sign in first: your customer ID links this order to your return history.")
    return customer


def owned_return(return_id: int) -> dict | None:
    """The return, if it belongs to the signed-in customer. Customers only ever see their own data."""
    customer = require_customer()
    ret = storage.get_return(return_id)
    if ret is None:
        return None
    if ret["customer_id"] != customer["customer_id"]:
        raise service.ForbiddenError("This return belongs to another customer.")
    return ret


def owned_order(order_id: int) -> dict | None:
    customer = require_customer()
    order = storage.get_order(order_id, with_features=False)
    if order is None:
        return None
    if order["customer_id"] != customer["customer_id"]:
        raise service.ForbiddenError("This order belongs to another customer.")
    return order


def form_or_json(key: str) -> str:
    data = request.get_json(silent=True) or {}
    return str(data.get(key) or request.form.get(key) or "")


_recent_posts: dict[str, deque] = defaultdict(deque)


@app.before_request
def rate_limit():
    """On a public demo, cap uploads per visitor so nobody can drain the Gemini quota."""
    if config.RATE_LIMIT_PER_HOUR <= 0 or request.method != "POST" or not request.path.startswith("/api/") \
            or request.path.startswith("/api/auth/"):
        return None
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()
    hits, now = _recent_posts[ip], time.time()
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= config.RATE_LIMIT_PER_HOUR:
        return jsonify(success=False, error="Demo limit reached for this hour. Please try again later."), 429
    hits.append(now)
    return None


@app.errorhandler(service.ForbiddenError)
def forbidden(err):
    return jsonify(success=False, error=str(err)), 403


@app.errorhandler(service.InputError)
def bad_input(err):
    return jsonify(success=False, error=str(err)), 400


@app.errorhandler(413)
def too_large(_):
    return jsonify(success=False, error=f"Upload too large (max {config.MAX_UPLOAD_MB} MB per photo)."), 413


@app.get("/")
def home():
    return render_template("index.html", reasons=config.RETURN_REASONS, windows=config.RETURN_WINDOW_DAYS)


# ── accounts ───────────────────────────────────────────────────────────────
@app.post("/api/auth/signup")
def signup():
    customer = service.sign_up(form_or_json("email"), form_or_json("phone"))
    session["customer_id"] = customer["customer_id"]
    return jsonify(success=True, customer=service.public_customer(customer))


@app.post("/api/auth/login")
def login():
    customer = service.sign_in(form_or_json("email"), form_or_json("phone"))
    session["customer_id"] = customer["customer_id"]
    return jsonify(success=True, customer=service.public_customer(customer))


@app.post("/api/auth/logout")
def logout():
    session.pop("customer_id", None)
    return jsonify(success=True)


@app.get("/api/auth/me")
def me():
    customer = current_customer()
    if customer is None:
        return jsonify(success=True, customer=None)
    cid = customer["customer_id"]
    profile = customer_profile(cid)
    return jsonify(success=True, customer=service.public_customer(customer), profile=profile,
                   profile_explained=explain.history(profile), orders=storage.orders_for_customer(cid),
                   returns=storage.returns_for_customer(cid))


# ── deliveries & returns ───────────────────────────────────────────────────
@app.post("/api/deliveries")
def create_delivery():
    customer = require_customer()
    days = request.form.get("delivered_days_ago", "0").strip() or "0"
    if not days.isdigit() or int(days) > 365:
        raise service.InputError("'Delivered days ago' must be a whole number between 0 and 365.")
    job = _progress_key(customer["customer_id"], request.form.get("job_id", ""))

    def on_stage(key, detail=""):
        if job:
            with _progress_lock:
                _progress[job] = {"stage": key, "detail": detail, "at": time.time()}

    try:
        order = service.register_delivery(uploaded_images(), customer["customer_id"],
                                          request.form.get("product_name", "").strip()[:120],
                                          request.form.get("category", "other"), int(days), on_stage=on_stage)
    finally:
        if job:
            with _progress_lock:
                _progress.pop(job, None)
    return jsonify(success=True, order=order, images=media_urls("orders", order["order_id"]))


# Live delivery progress: the browser sends a random job_id with the upload and polls this while it waits.
_progress: dict[tuple[str, str], dict] = {}
_progress_lock = threading.Lock()


def _progress_key(customer_id: str, job_id: str):
    return (customer_id, job_id) if re.fullmatch(r"[A-Za-z0-9-]{8,64}", job_id or "") else None


@app.get("/api/deliveries/progress/<job_id>")
def delivery_progress(job_id):
    customer = require_customer()
    key = _progress_key(customer["customer_id"], job_id)
    with _progress_lock:
        stale = [k for k, v in _progress.items() if time.time() - v["at"] > 600]
        for k in stale:
            _progress.pop(k, None)
        state = _progress.get(key) if key else None
    return jsonify(success=True, stage=state["stage"] if state else None, detail=state["detail"] if state else "")


@app.post("/api/returns")
def create_return():
    customer = require_customer()
    order_id = request.form.get("order_id", "").strip().lstrip("#")
    if not order_id.isdigit():
        raise service.InputError("Order ID must be a number.")
    return_id = service.start_return(int(order_id), uploaded_images(), request.form.get("reason", "changed_mind"),
                                     customer["customer_id"])
    return jsonify(success=True, return_id=return_id), 202


@app.get("/api/returns/<int:return_id>")
def get_return(return_id):
    ret = owned_return(return_id)
    if ret is None:
        return jsonify(success=False, error=f"Return #{return_id} not found."), 404
    order = storage.get_order(ret["order_id"], with_features=False)
    explained = explain.explain_result(ret["result"], order) if ret["result"] else None
    return jsonify(success=True, ret=ret, order=order, explained=explained,
                   delivery_images=media_urls("orders", ret["order_id"]), return_images=media_urls("returns", return_id),
                   report_url=f"/report/{return_id}?t={report_token(ret['customer_id'])}" if ret["result"] else None)


@app.post("/api/returns/<int:return_id>/second-opinion")
def second_opinion(return_id):
    customer = require_customer()
    opinion = service.second_opinion(return_id, customer["customer_id"])
    return jsonify(success=True, opinion=opinion)


@app.get("/api/returns")
def list_returns():
    customer = require_customer()
    return jsonify(success=True, returns=storage.returns_for_customer(customer["customer_id"]))


@app.get("/api/orders")
def list_orders():
    customer = require_customer()
    return jsonify(success=True, orders=storage.orders_for_customer(customer["customer_id"]))


@app.get("/api/orders/<int:order_id>")
def get_order(order_id):
    order = owned_order(order_id)
    if order is None:
        return jsonify(success=False, error=f"Order #{order_id} not found."), 404
    return jsonify(success=True, order=order, returns=storage.returns_for_order(order_id),
                   images=media_urls("orders", order_id))


@app.get("/api/stats")
def stats():
    """The signed-in customer's own activity, plus exactly what the history agent sees for their ID."""
    customer = require_customer()
    cid = customer["customer_id"]
    profile = customer_profile(cid)
    return jsonify(success=True, customer=service.public_customer(customer), stats=storage.dashboard_stats(cid),
                   profile=profile, profile_explained=explain.history(profile))


@app.get("/api/metrics")
def metrics():
    if not config.RESULTS_PATH.exists():
        return jsonify(success=False, error="No evaluation yet. Run: python scripts/evaluate.py"), 404
    results = json.loads(config.RESULTS_PATH.read_text(encoding="utf-8"))
    if request.args.get("pairs") != "1":
        results.pop("per_pair", None)
    return jsonify(success=True, results=results)


def _wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


@app.get("/api/stress")
def stress():
    """Precision stress test (scripts/stress_test_precision.py): pooled over every augmentation condition."""
    path = config.RESULTS_PATH.parent / "stress_precision.json"
    if not path.exists():
        return jsonify(success=False, error="No stress test yet. Run: python scripts/stress_test_precision.py"), 404
    data = json.loads(path.read_text(encoding="utf-8"))
    conds = [c for c in data["conditions"] if c["condition"] != "baseline"]
    tp = sum(c["local"]["tp"] for c in conds)
    fp = sum(c["local"]["fp"] for c in conds)
    fn = sum(c["local"]["fn"] for c in conds)
    rows = [{"label": c["label"], "level": c["level"], "genuine": c["genuine"], "fp": c["local"]["fp"],
             "precision": c["local"]["precision"], "recall": c["local"]["recall"], **c["genuine_routing"]} for c in conds]
    pooled = {"tp": tp, "fp": fp, "fn": fn, "flags": tp + fp, "precision": round(tp / (tp + fp), 4) if tp + fp else 0,
              "precision_ci": _wilson(tp, tp + fp), "recall": round(tp / (tp + fn), 4) if tp + fn else 0,
              "conditions": len(conds), "pairs": sum(c["genuine"] + c["fraud"] for c in conds)}
    return jsonify(success=True, generated_at=data["generated_at"], stage=data["stage"], summary=data["summary"],
                   pooled=pooled, conditions=rows, real_second_session=data.get("real_second_session", []))


@app.get("/api/config")
def public_config():
    return jsonify(success=True, reasons=config.RETURN_REASONS, windows=config.RETURN_WINDOW_DAYS,
                   thresholds={"fast_reject_shape": config.FAST_REJECT_SHAPE,
                               "fast_accept_shape": config.FAST_ACCEPT_SHAPE,
                               "accept_below": config.ACCEPT_BELOW, "reject_from": config.REJECT_FROM},
                   model=config.LLM_MODEL)


@app.get("/report/<int:return_id>")
def report(return_id):
    viewer = viewer_id()
    ret = storage.get_return(return_id)
    if ret is None or not ret["result"]:
        abort(404)
    if viewer is None or ret["customer_id"] != viewer:
        abort(403)
    token = request.args.get("t") if current_customer() is None else None
    order = storage.get_order(ret["order_id"], with_features=False)
    return render_template("report.html", ret=ret, order=order, r=ret["result"], reasons=config.RETURN_REASONS,
                           x=explain.explain_result(ret["result"], order),
                           delivery=media_urls("orders", ret["order_id"], token),
                           returned=media_urls("returns", return_id, token),
                           audit=storage.get_audit(return_id=return_id))


@app.get("/media/<kind>/<int:item_id>/<name>")
def media(kind, item_id, name):
    if kind not in ("orders", "returns") or name not in MEDIA_FILES:
        abort(404)
    viewer = viewer_id()
    if viewer is None:
        abort(403)
    if kind == "orders":
        order = storage.get_order(item_id, with_features=False)
        if order is None or order["customer_id"] != viewer:
            abort(404)
        return send_from_directory(config.IMAGE_DIR / "orders" / str(item_id), name)
    ret = storage.get_return(item_id)
    if ret is None or ret["customer_id"] != viewer:
        abort(404)
    folder = service.return_dir(ret["order_id"], item_id)
    if not (folder / name).exists():                       # returns saved before photos moved under their order
        folder = config.IMAGE_DIR / "returns" / str(item_id)
    return send_from_directory(folder, name)


@app.get("/api/health")
def health():
    return jsonify(status="ok", model=config.LLM_MODEL,
                   llm_configured=bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")))


if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")),
            debug=os.getenv("FLASK_DEBUG") == "1")
