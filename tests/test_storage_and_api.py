from datetime import datetime, timedelta

from returnguard import storage
from returnguard.agents.history import customer_profile
from returnguard.agents.policy import check_policy


def test_policy_windows_by_category():
    delivered = datetime(2026, 10, 1)
    assert check_policy("electronics", delivered, delivered + timedelta(days=7), "changed_mind")["eligible"]
    late = check_policy("electronics", delivered, delivered + timedelta(days=8), "changed_mind")
    assert not late["eligible"] and late["requires_functional_test"]
    assert check_policy("apparel", delivered, delivered + timedelta(days=25), "damaged")["eligible"]


def test_order_ids_are_assigned_at_delivery_and_never_reused():
    storage.init_db()
    a = storage.create_order("c1", "speaker", "electronics", "2026-10-01T00:00:00+00:00", {})
    b = storage.create_order("c1", "bottle", "home_kitchen", "2026-10-01T00:00:00+00:00", {})
    assert b == a + 1
    assert storage.get_order(a)["product_name"] == "speaker"


def test_history_counts_flagged_returns_and_restart_never_leaves_returns_stuck():
    storage.init_db()
    oid = storage.create_order("repeat-cust", "x", "other", "2026-10-01T00:00:00+00:00", {})
    r1 = storage.create_return(oid, "changed_mind")
    storage.finish_return(r1, "REJECT", 99, {"decision": {}})
    assert customer_profile("repeat-cust")["tier"] == "repeat_flagged"
    assert customer_profile("repeat-cust")["accept_below"] < 50

    stuck = storage.create_return(oid, "changed_mind")
    storage.init_db()  # simulates a server restart
    assert storage.get_return(stuck)["status"] == "ERROR"


def test_api_validates_input():
    from app import app
    client = app.test_client()
    r = client.post("/api/returns", data={"order_id": "1", "reason": "changed_mind"})
    assert r.status_code == 400 and "Sign in first" in r.get_json()["error"]
    client.post("/api/auth/signup", json={"email": "validator@example.com", "phone": "9876500001"})
    assert client.post("/api/returns", data={"order_id": "../../etc", "reason": "changed_mind"}).status_code == 400
    r = client.post("/api/returns", data={"order_id": "999999", "reason": "changed_mind"})
    assert r.status_code == 400 and "does not exist" in r.get_json()["error"]
    assert client.get("/media/orders/1/..%2F..%2Freturnguard.db").status_code == 404
    assert client.get("/media/secrets/1/front.jpg").status_code == 404
    assert client.get("/api/returns/424242").status_code == 404
    assert client.get("/api/health").status_code == 200


def test_signup_login_and_customer_id():
    from app import app
    client = app.test_client()
    r = client.post("/api/auth/signup", json={"email": "Asha@Example.com", "phone": "+91 98765 43210"})
    cid = r.get_json()["customer"]["customer_id"]
    assert r.status_code == 200 and cid.startswith("RG-") and len(cid) == 9
    assert r.get_json()["customer"]["phone"].endswith("3210") and "9876" not in r.get_json()["customer"]["phone"]
    assert client.get("/api/auth/me").get_json()["customer"]["customer_id"] == cid
    assert client.get("/api/auth/me").get_json()["profile"]["tier"] == "new"

    # same email cannot sign up twice; wrong phone cannot sign in
    assert client.post("/api/auth/signup", json={"email": "asha@example.com", "phone": "9876543210"}).status_code == 400
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").get_json()["customer"] is None
    assert client.post("/api/auth/login", json={"email": "asha@example.com", "phone": "9999999999"}).status_code == 400
    r = client.post("/api/auth/login", json={"email": "asha@example.com", "phone": "09876543210"})
    assert r.status_code == 200 and r.get_json()["customer"]["customer_id"] == cid

    assert client.post("/api/auth/signup", json={"email": "not-an-email", "phone": "9876543210"}).status_code == 400
    assert client.post("/api/auth/signup", json={"email": "b@example.com", "phone": "12345"}).status_code == 400


def test_customers_only_see_their_own_history():
    from app import app
    alice, bob = app.test_client(), app.test_client()
    a = alice.post("/api/auth/signup", json={"email": "alice@example.com", "phone": "9111111111"}).get_json()["customer"]
    b = bob.post("/api/auth/signup", json={"email": "bob@example.com", "phone": "9222222222"}).get_json()["customer"]
    a_order = storage.create_order(a["customer_id"], "alice speaker", "electronics", "2026-10-01T00:00:00+00:00", {})
    b_order = storage.create_order(b["customer_id"], "bob bottle", "home_kitchen", "2026-10-01T00:00:00+00:00", {})
    a_ret = storage.create_return(a_order, "changed_mind")
    storage.finish_return(a_ret, "REJECT", 99, {"decision": {"decision": "REJECT"}})

    assert [o["order_id"] for o in alice.get("/api/orders").get_json()["orders"]] == [a_order]
    assert [o["order_id"] for o in bob.get("/api/orders").get_json()["orders"]] == [b_order]
    assert [r["return_id"] for r in alice.get("/api/returns").get_json()["returns"]] == [a_ret]
    assert bob.get("/api/returns").get_json()["returns"] == []

    # the history agent's view differs per customer: Alice has a flagged return, Bob doesn't
    assert alice.get("/api/stats").get_json()["profile"]["tier"] == "repeat_flagged"
    assert bob.get("/api/stats").get_json()["profile"]["tier"] == "new"
    assert alice.get("/api/stats").get_json()["stats"]["orders"] == 1

    # Bob can't open Alice's return, report or photos
    assert bob.get(f"/api/returns/{a_ret}").status_code == 403
    assert bob.get(f"/report/{a_ret}").status_code == 403
    assert bob.get(f"/media/orders/{a_order}/front.jpg").status_code == 404
    # and signed-out visitors see nothing
    anon = app.test_client()
    assert anon.get("/api/orders").status_code == 400 and anon.get("/api/stats").status_code == 400


def test_deliveries_need_sign_in_and_returns_need_the_owner():
    from app import app
    client = app.test_client()
    r = client.post("/api/deliveries", data={"category": "electronics"})
    assert r.status_code == 400 and "Sign in first" in r.get_json()["error"]

    owner = storage.create_customer("owner@example.com", "9000000001")
    oid = storage.create_order(owner["customer_id"], "speaker", "electronics", "2026-10-01T00:00:00+00:00", {})
    client.post("/api/auth/signup", json={"email": "someone-else@example.com", "phone": "9000000002"})
    r = client.post("/api/returns", data={"order_id": str(oid), "reason": "changed_mind"})
    assert r.status_code == 403 and "another customer" in r.get_json()["error"]


def test_report_link_works_in_a_new_tab_without_the_session_cookie():
    from app import app, report_token
    owner = app.test_client()
    c = owner.post("/api/auth/signup", json={"email": "carol@example.com", "phone": "9333333333"}).get_json()["customer"]
    other = storage.create_customer("dave@example.com", "9444444444")
    order = storage.create_order(c["customer_id"], "carol speaker", "electronics", "2026-10-01T00:00:00+00:00", {})
    ret = storage.create_return(order, "changed_mind")
    storage.finish_return(ret, "REJECT", 99, {"decision": {"decision": "REJECT"}})

    url = owner.get(f"/api/returns/{ret}").get_json()["report_url"]
    token = url.split("?t=")[1]
    new_tab = app.test_client()                                   # no cookie, like a new tab outside the iframe
    assert new_tab.get(f"/media/orders/{order}/front.jpg").status_code == 403
    assert new_tab.get(f"/media/orders/{order}/front.jpg?t={token}").status_code == 404   # allowed; no file in test
    assert new_tab.get(f"/report/{ret}?t={token}x").status_code == 403                    # tampered
    assert new_tab.get(f"/report/{ret}?t={report_token(other['customer_id'])}").status_code == 403  # not the owner
