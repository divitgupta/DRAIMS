"""Checkpoint 8 tests: form validation, security and the request workflow.
Run:  DRAIMS_DB_PORT=3306 DRAIMS_DB_USER=root DRAIMS_DB_PASSWORD=... .venv/bin/pytest -q
The database is reloaded from DRAIMS_database.sql first, so run it only against a test database."""
import time
from datetime import date, timedelta

import pymysql

from conftest import post, token

TODAY = date.today()


def db(app):
    c = app.config
    return pymysql.connect(host=c["DB_HOST"], port=c["DB_PORT"], user=c["DB_USER"], password=c["DB_PASSWORD"],
                           database=c["DB_NAME"], cursorclass=pymysql.cursors.DictCursor, autocommit=True)


def one(app, sql, args=()):
    conn = db(app)
    with conn.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
    conn.close()
    return row


# ======================================================================= security
def test_S01_valid_login(login):
    """Valid login for each of the four roles opens the dashboard"""
    for u in ["admin", "coord.kodagu", "wm.madikeri", "fo.kodagu"]:
        c, r = login(u)
        assert r.status_code == 302 and r.headers["Location"] == "/"
        assert "Dashboard" in c.get("/").text


def test_S02_wrong_password(login):
    """Wrong password gives a generic error and no session"""
    c, r = login("admin", "wrong-Pass1!")
    assert r.status_code == 200 and "Invalid username or password." in r.text
    assert c.get("/").status_code == 302


def test_S03_unknown_user(login):
    """Unknown username gives the same generic error (no hint that the user does not exist)"""
    _, r = login("nosuchuser", "Whatever1!")
    assert "Invalid username or password." in r.text


def test_S04_lockout(login):
    """Five failed logins lock the account for 10 minutes, even for the right password"""
    for _ in range(5):
        login("fo.belagavi", "bad-Pass1!")
    _, r = login("fo.belagavi")
    assert "Too many failed attempts" in r.text


def test_S05_login_required(app):
    """Pages need a login; the user is sent to the login page"""
    r = app.test_client().get("/requests")
    assert r.status_code == 302 and r.headers["Location"].startswith("/login?next=/requests")


def test_S06_role_checks(login):
    """Roles are enforced on the server: field officer cannot open allocation, warehouse manager cannot run it"""
    c, _ = login("fo.kodagu")
    assert c.get("/allocation").status_code == 403
    assert c.get("/users").status_code == 403
    c, _ = login("wm.madikeri")
    r = c.post("/allocation/run", data={"csrf_token": token(c.get("/").text)})
    assert r.status_code == 403


def test_S07_csrf(login):
    """A POST without the CSRF token, or with a wrong one, is rejected with 400"""
    c, _ = login("coord.kodagu")
    assert c.post("/allocation/run").status_code == 400
    assert c.post("/allocation/run", data={"csrf_token": "forged"}).status_code == 400


def test_S08_sql_injection_login(login):
    """SQL injection in the login form does not log anyone in"""
    _, r = login("' OR '1'='1' -- ", "' OR '1'='1")
    assert "Invalid username or password." in r.text


def test_S09_sql_injection_search(login):
    """SQL injection in the request search box is treated as plain text"""
    c, _ = login("coord.kodagu")
    r = c.get("/requests", query_string={"q": "' OR 1=1 -- "})
    assert r.status_code == 200 and "No requests match." in r.text


def test_S10_xss_escaped(login):
    """Script tags typed into a form are rejected by validation, and echoed text is HTML-escaped"""
    c, _ = login("coord.kodagu")
    r = post(c, "/disasters", {"form": "zone", "disaster_id": "2", "zone_name": "<script>alert(1)</script>",
                               "district": "Kodagu", "affected_population": "10", "damage_level": "2"})
    assert "contains characters that are not allowed" in r.text
    r = c.get("/requests", query_string={"q": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text


def test_S11_password_hashing(login, app):
    """New users' passwords are stored only as salted PBKDF2-SHA256 hashes"""
    c, _ = login("admin")
    r = post(c, "/users", {"full_name": "Meera Iyer", "username": "fo.udupi", "role": "FIELD_OFFICER",
                           "password": "Strong#Pass9", "confirm": "Strong#Pass9"})
    assert "User fo.udupi created." in r.text
    h = one(app, "SELECT password_hash FROM app_user WHERE username='fo.udupi'")["password_hash"]
    assert h.startswith("pbkdf2:sha256:600000$") and "Strong#Pass9" not in h
    _, r = login("fo.udupi", "Strong#Pass9")
    assert r.status_code == 302


def test_S12_weak_password(login):
    """Weak passwords are rejected with the list of missing rules"""
    c, _ = login("admin")
    r = post(c, "/users", {"full_name": "Test User", "username": "test.user", "role": "FIELD_OFFICER",
                           "password": "password", "confirm": "password"})
    assert "Password needs" in r.text and "an uppercase letter" in r.text and "a digit" in r.text


def test_S13_session_timeout(login):
    """After 30 minutes without activity the session ends"""
    c, _ = login("coord.kodagu")
    with c.session_transaction() as s:
        s["seen"] = int(time.time()) - 31 * 60
    r = c.get("/", follow_redirects=True)
    assert "Your session expired" in r.text


def test_S14_security_headers(login):
    """Every response carries CSP, anti-framing, no-sniff and no-cache headers"""
    c, _ = login("admin")
    h = c.get("/").headers
    assert "default-src 'self'" in h["Content-Security-Policy"] and "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
    assert h["Cache-Control"] == "no-store" and h["Referrer-Policy"] == "no-referrer"


def test_S15_cookie_flags(login):
    """The session cookie is HttpOnly and SameSite=Strict"""
    _, r = login("admin")
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie


def test_S16_open_redirect(app):
    """The ?next= parameter cannot send users to another site after login"""
    c = app.test_client()
    t = token(c.get("/login").text)
    r = c.post("/login?next=//evil.example", data={"csrf_token": t, "username": "admin", "password": "Relief@2026"})
    assert r.headers["Location"] == "/"


def test_S17_logout(login):
    """Logout needs a POST with the CSRF token and ends the session"""
    c, _ = login("admin")
    assert c.get("/logout").status_code == 405
    post(c, "/logout", {})
    assert c.get("/").status_code == 302


def test_S18_audit_log(app):
    """Logins, failed logins and denied pages are written to logs/security.log"""
    import os
    from config import BASE_DIR
    log = open(os.path.join(BASE_DIR, "logs", "security.log")).read()
    assert "LOGIN_OK" in log and "LOGIN_FAILED" in log and "ACCESS_DENIED" in log and "CSRF_REJECTED" in log


# ======================================================================= validation
def test_V01_disaster_form(login):
    """Disaster form: empty name and a future start date are rejected"""
    c, _ = login("coord.kodagu")
    r = post(c, "/disasters", {"form": "disaster", "disaster_name": "", "disaster_type": "FLOOD",
                               "start_date": (TODAY + timedelta(days=3)).isoformat()})
    assert "Disaster name is required." in r.text and "Start date cannot be in the future." in r.text


def test_V02_zone_ranges(login, app):
    """Zone form: damage level 7 and a negative population are rejected before reaching the database"""
    before = one(app, "SELECT COUNT(*) n FROM zone")["n"]
    c, _ = login("coord.kodagu")
    r = post(c, "/disasters", {"form": "zone", "disaster_id": "2", "zone_name": "Napoklu", "district": "Kodagu",
                               "affected_population": "-5", "damage_level": "7"})
    assert "Damage level must be between 1 and 5." in r.text
    assert "Affected population must be between 0 and 10,000,000." in r.text
    assert one(app, "SELECT COUNT(*) n FROM zone")["n"] == before


def test_V03_zone_duplicate(login):
    """A duplicate zone is stopped by the UNIQUE constraint and shown as a friendly message"""
    c, _ = login("coord.kodagu")
    r = post(c, "/disasters", {"form": "zone", "disaster_id": "2", "zone_name": "Virajpet", "district": "Kodagu",
                               "affected_population": "100", "damage_level": "2"})
    assert "This value already exists." in r.text


def test_V04_donor_phone(login):
    """Donor form: a phone number that is not 10 digits starting with 6-9 is rejected"""
    c, _ = login("wm.madikeri")
    r = post(c, "/donations", {"form": "donor", "donor_name": "Kodava Samaja", "donor_type": "NGO", "phone": "12345"})
    assert "Phone must be 10 digits starting with 6" in r.text


def test_V05_donation_ranges(login):
    """Donation form: quantity 0 and a future date are rejected"""
    c, _ = login("wm.madikeri")
    r = post(c, "/donations", {"form": "donation", "donor_id": "2", "warehouse_id": "1", "item_id": "3",
                               "quantity": "0", "donation_date": (TODAY + timedelta(days=1)).isoformat()})
    assert "Quantity must be between 1 and 1,000,000." in r.text and "Donation date cannot be in the future." in r.text


def test_V06_donation_updates_stock(login, app):
    """A valid donation is saved, gets a receipt number and raises stock at once"""
    before = one(app, "SELECT quantity FROM inventory WHERE warehouse_id=1 AND item_id=3")["quantity"]
    c, _ = login("wm.madikeri")
    r = post(c, "/donations", {"form": "donation", "donor_id": "6", "warehouse_id": "1", "item_id": "3",
                               "quantity": "4000", "donation_date": TODAY.isoformat()})
    assert "Donation recorded and stock updated." in r.text and "Receipt number: DON-" in r.text
    assert one(app, "SELECT quantity FROM inventory WHERE warehouse_id=1 AND item_id=3")["quantity"] == before + 4000


def test_V07_request_no_items(login):
    """Relief request: a request without items is rejected"""
    c, _ = login("fo.kodagu")
    r = post(c, "/requests/new", {"zone_id": "3", "urgency": "3", "item_id": "", "qty": ""})
    assert "Add at least one item." in r.text


def test_V08_request_duplicate_items(login):
    """Relief request: the same item twice is rejected"""
    c, _ = login("fo.kodagu")
    r = c.post("/requests/new", data={"csrf_token": token(c.get("/").text), "zone_id": "3", "urgency": "3",
                                      "item_id": ["3", "3"], "qty": ["10", "20"]})
    assert "this item is already in the request" in r.text


def test_V09_request_ranges(login):
    """Relief request: quantity outside 1-100,000 and urgency 9 are rejected"""
    c, _ = login("fo.kodagu")
    r = c.post("/requests/new", data={"csrf_token": token(c.get("/").text), "zone_id": "3", "urgency": "9",
                                      "item_id": ["3", "5"], "qty": ["0", "200000"]})
    assert "Urgency must be between 1 and 5." in r.text and "quantity must be a whole number from 1 to 100,000" in r.text


def test_V10_request_closed_disaster(login):
    """Relief request: a zone of a closed disaster cannot be chosen"""
    c, _ = login("fo.kodagu")
    r = c.post("/requests/new", data={"csrf_token": token(c.get("/").text), "zone_id": "1", "urgency": "3",
                                      "item_id": ["3"], "qty": ["10"]})
    assert "Please choose a valid zone." in r.text


def test_V11_request_valid(login, app):
    """A valid request with two items is saved as PENDING with both items"""
    c, _ = login("fo.kodagu")
    r = c.post("/requests/new", data={"csrf_token": token(c.get("/").text), "zone_id": "3", "urgency": "4",
                                      "item_id": ["6", "8"], "qty": ["20", "50"]}, follow_redirects=True)
    assert "Relief request submitted." in r.text
    rid = one(app, "SELECT MAX(request_id) id FROM relief_request")["id"]
    assert one(app, "SELECT status FROM relief_request WHERE request_id=%s", (rid,))["status"] == "PENDING"
    assert one(app, "SELECT COUNT(*) n FROM request_item WHERE request_id=%s", (rid,))["n"] == 2


def test_V12_duplicate_username(login):
    """User form: an existing username is stopped by the UNIQUE constraint"""
    c, _ = login("admin")
    r = post(c, "/users", {"full_name": "Second Admin", "username": "admin", "role": "ADMIN",
                           "password": "Strong#Pass9", "confirm": "Strong#Pass9"})
    assert "This value already exists." in r.text


def test_V13_reorder_level(login, app):
    """Inventory form: a negative reorder level is rejected; a valid one is saved"""
    c, _ = login("wm.madikeri")
    r = post(c, "/inventory", {"pair": "1-3", "reorder_level": "-1"})
    assert "Reorder level must be between 0 and 1,000,000." in r.text
    r = post(c, "/inventory", {"pair": "1-3", "reorder_level": "2000"})
    assert "Reorder level updated." in r.text
    assert one(app, "SELECT reorder_level FROM inventory WHERE warehouse_id=1 AND item_id=3")["reorder_level"] == 2000


def test_V14_field_length(login):
    """Disaster form: a 101-character name is rejected"""
    c, _ = login("coord.kodagu")
    r = post(c, "/disasters", {"form": "disaster", "disaster_name": "A" * 101, "disaster_type": "FLOOD",
                               "start_date": TODAY.isoformat()})
    assert "Disaster name must be 3–100 characters." in r.text


# ======================================================================= workflow
def test_W01_run_allocation(login, app):
    """Coordinator runs allocation; open requests are served in priority order"""
    c, _ = login("coord.kodagu")
    r = post(c, "/allocation/run", {})
    assert "Allocation finished:" in r.text
    assert one(app, "SELECT COUNT(*) n FROM relief_request WHERE status='PENDING'")["n"] == 0


def test_W02_dispatch_and_deliver(login, app):
    """Warehouse manager marks stock dispatched; field officer confirms delivery"""
    aid = one(app, "SELECT MIN(allocation_id) id FROM allocation WHERE status='ALLOCATED' AND warehouse_id=1")["id"]
    c, _ = login("wm.madikeri")
    r = post(c, "/dispatch", {"allocation_id": str(aid)})
    assert "marked DISPATCHED" in r.text
    c, _ = login("fo.kodagu")
    r = post(c, "/dispatch", {"allocation_id": str(aid)})
    assert "marked DELIVERED" in r.text
    assert one(app, "SELECT status FROM allocation WHERE allocation_id=%s", (aid,))["status"] == "DELIVERED"


def test_W03_cancel_returns_stock(login, app):
    """Cancelling an allocated request returns its stock to the warehouse"""
    rid = one(app, "SELECT MAX(request_id) id FROM relief_request")["id"]
    stock = one(app, "SELECT SUM(quantity) q FROM inventory")["q"]
    reserved = one(app, "SELECT COALESCE(SUM(quantity),0) q FROM allocation WHERE request_id=%s AND status='ALLOCATED'",
                   (rid,))["q"]
    c, _ = login("coord.kodagu")
    r = post(c, f"/requests/{rid}/cancel", {})
    assert f"Request {rid} cancelled" in r.text
    assert one(app, "SELECT SUM(quantity) q FROM inventory")["q"] == stock + reserved


def test_W04_cancel_dispatched_blocked(login):
    """A request whose stock is already on the road cannot be cancelled"""
    c, _ = login("coord.kodagu")
    r = post(c, "/requests/3/cancel", {})
    assert "Stock for this request is already dispatched" in r.text
