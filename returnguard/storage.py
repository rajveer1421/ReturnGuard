"""SQLite persistence: customers, orders (created at delivery), returns, and an audit
log with one row per pipeline stage."""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from returnguard import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id     TEXT PRIMARY KEY,  -- e.g. RG-7KQ2MX, generated at sign-up
    email           TEXT NOT NULL UNIQUE,
    phone           TEXT NOT NULL,     -- 10 digits
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     TEXT NOT NULL,
    product_name    TEXT,
    category        TEXT NOT NULL,
    delivered_at    TEXT NOT NULL,
    fingerprint     TEXT,              -- identity agent output (JSON) or NULL if unavailable
    features        TEXT,              -- per-view embedding + colour (JSON), computed once at delivery
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS returns (
    return_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL REFERENCES orders(order_id),
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL,     -- PROCESSING | ACCEPT | HUMAN_REVIEW | REJECT | RETAKE_REQUIRED | ERROR
    risk_score      INTEGER,
    progress        TEXT,              -- pipeline nodes finished so far (JSON list), for the live UI
    result          TEXT,              -- full pipeline result (JSON)
    error           TEXT,
    created_at      TEXT NOT NULL,
    completed_at    TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL,
    return_id       INTEGER,
    stage           TEXT NOT NULL,
    payload         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_returns_order ON returns(order_id);
CREATE INDEX IF NOT EXISTS idx_audit_return ON audit_log(return_id);
"""
FLAGGED = ("HUMAN_REVIEW", "REJECT")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL")
        # a restart can't resume an in-flight pipeline: never leave it looking "stuck"
        conn.execute("UPDATE returns SET status='ERROR', error='Interrupted by a server restart; resubmit the return.', "
                     "completed_at=? WHERE status='PROCESSING'", (now(),))


_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I/L: easy to read out on a phone call


def create_customer(email: str, phone: str) -> dict:
    with connect() as conn:
        while True:
            cid = "RG-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(6))
            if not conn.execute("SELECT 1 FROM customers WHERE customer_id=?", (cid,)).fetchone():
                break
        conn.execute("INSERT INTO customers (customer_id, email, phone, created_at) VALUES (?, ?, ?, ?)",
                     (cid, email, phone, now()))
    return get_customer(cid)


def find_customer_by_email(email: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
    return dict(row) if row else None


def get_customer(customer_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE customer_id=?", (customer_id,)).fetchone()
    return dict(row) if row else None


def orders_for_customer(customer_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT o.order_id, o.product_name, o.category, o.delivered_at, o.fingerprint IS NOT NULL AS has_fingerprint, "
            "(SELECT status FROM returns r WHERE r.order_id=o.order_id ORDER BY return_id DESC LIMIT 1) AS last_return_status "
            "FROM orders o WHERE o.customer_id=? ORDER BY o.order_id DESC", (customer_id,)).fetchall()
    return [dict(r) for r in rows]


def returns_for_customer(customer_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT r.return_id, r.order_id, r.reason, r.status, r.risk_score, r.created_at, o.product_name "
                            "FROM returns r JOIN orders o ON o.order_id=r.order_id WHERE o.customer_id=? "
                            "ORDER BY r.return_id DESC", (customer_id,)).fetchall()
    return [dict(r) for r in rows]


def _order(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["fingerprint"] = json.loads(d["fingerprint"]) if d["fingerprint"] else None
    d["features"] = json.loads(d["features"]) if d["features"] else None
    return d


def create_order(customer_id: str, product_name: str, category: str, delivered_at: str, features: dict) -> int:
    with connect() as conn:
        cur = conn.execute("INSERT INTO orders (customer_id, product_name, category, delivered_at, features, created_at) "
                           "VALUES (?, ?, ?, ?, ?, ?)",
                           (customer_id, product_name, category, delivered_at, json.dumps(features), now()))
        return cur.lastrowid


def set_fingerprint(order_id: int, fingerprint: dict | None):
    with connect() as conn:
        conn.execute("UPDATE orders SET fingerprint=? WHERE order_id=?",
                     (json.dumps(fingerprint) if fingerprint else None, order_id))


def get_order(order_id: int, with_features: bool = True) -> dict | None:
    with connect() as conn:
        order = _order(conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone())
    if order and not with_features:
        order.pop("features", None)
    return order


def create_return(order_id: int, reason: str) -> int:
    with connect() as conn:
        cur = conn.execute("INSERT INTO returns (order_id, reason, status, created_at) VALUES (?, ?, 'PROCESSING', ?)",
                           (order_id, reason, now()))
        return cur.lastrowid


def add_progress(return_id: int, node: str):
    with connect() as conn:
        row = conn.execute("SELECT progress FROM returns WHERE return_id=?", (return_id,)).fetchone()
        done = json.loads(row["progress"]) if row and row["progress"] else []
        conn.execute("UPDATE returns SET progress=? WHERE return_id=?", (json.dumps(done + [node]), return_id))


def finish_return(return_id: int, status: str, risk_score: int | None, result: dict | None, error: str | None = None):
    with connect() as conn:
        conn.execute("UPDATE returns SET status=?, risk_score=?, result=?, error=?, completed_at=? WHERE return_id=?",
                     (status, risk_score, json.dumps(result) if result else None, error, now(), return_id))


def update_result(return_id: int, result: dict):
    with connect() as conn:
        conn.execute("UPDATE returns SET result=? WHERE return_id=?", (json.dumps(result), return_id))


def get_return(return_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT r.*, o.customer_id, o.product_name, o.category, o.delivered_at FROM returns r "
                           "JOIN orders o ON o.order_id=r.order_id WHERE r.return_id=?", (return_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["result"] = json.loads(d["result"]) if d["result"] else None
    d["progress"] = json.loads(d["progress"]) if d["progress"] else []
    return d


def returns_for_order(order_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT return_id, reason, status, risk_score, created_at FROM returns WHERE order_id=? "
                            "ORDER BY return_id DESC", (order_id,)).fetchall()
    return [dict(r) for r in rows]


def customer_return_stats(customer_id: str, exclude_return_id: int | None = None) -> dict:
    with connect() as conn:
        conn.executescript(SCHEMA)
        row = conn.execute(
            "SELECT COUNT(*) AS n, SUM(r.status IN (?, ?)) AS flagged FROM returns r JOIN orders o "
            "ON o.order_id=r.order_id WHERE o.customer_id=? AND r.status != 'PROCESSING' AND r.return_id != ?",
            (*FLAGGED, customer_id, exclude_return_id or -1)).fetchone()
    return {"returns": row["n"] or 0, "flagged": row["flagged"] or 0}


def dashboard_stats(customer_id: str) -> dict:
    """Counts for one customer's own deliveries and returns."""
    with connect() as conn:
        rows = conn.execute("SELECT r.status, COUNT(*) AS n FROM returns r JOIN orders o ON o.order_id=r.order_id "
                            "WHERE o.customer_id=? GROUP BY r.status", (customer_id,)).fetchall()
        orders = conn.execute("SELECT COUNT(*) FROM orders WHERE customer_id=?", (customer_id,)).fetchone()[0]
        no_llm = conn.execute("SELECT COUNT(*) FROM returns r JOIN orders o ON o.order_id=r.order_id WHERE o.customer_id=? "
                              "AND json_extract(r.result, '$.llm_call_count') = 0", (customer_id,)).fetchone()[0]
    by_status = {r["status"]: r["n"] for r in rows}
    done = sum(v for k, v in by_status.items() if k in ("ACCEPT", "HUMAN_REVIEW", "REJECT"))
    return {"orders": orders, "returns": sum(by_status.values()), "by_status": by_status,
            "decided_without_llm": no_llm, "completed": done}


def add_audit(order_id: int, return_id: int | None, stage: str, payload: dict):
    with connect() as conn:
        conn.execute("INSERT INTO audit_log (order_id, return_id, stage, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                     (order_id, return_id, stage, json.dumps(payload, default=str), now()))


def get_audit(return_id: int | None = None, order_id: int | None = None) -> list[dict]:
    with connect() as conn:
        if return_id is not None:
            rows = conn.execute("SELECT * FROM audit_log WHERE return_id=? ORDER BY id", (return_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log WHERE order_id=? AND return_id IS NULL ORDER BY id",
                                (order_id,)).fetchall()
    return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]
