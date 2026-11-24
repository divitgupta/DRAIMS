"""DRAIMS web application: forms, security and validation on top of the MySQL database.
Runs fully offline on the local network.  Start with:  ./run.sh"""
from datetime import date

import pymysql
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db
import security as sec
import validators as v
from config import BASE_DIR, Config

DISASTER_TYPES = ["FLOOD", "CYCLONE", "EARTHQUAKE", "LANDSLIDE", "DROUGHT", "FIRE", "OTHER"]
DONOR_TYPES = ["INDIVIDUAL", "NGO", "CORPORATE", "GOVERNMENT"]
STATUSES = ["PENDING", "PARTIAL", "ALLOCATED", "DELIVERED", "CANCELLED"]
HASH_METHOD = "pbkdf2:sha256:600000"


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    sec.setup_audit_log(BASE_DIR)

    app.before_request(sec.load_user)
    app.before_request(sec.check_csrf)
    app.after_request(sec.security_headers)
    app.teardown_appcontext(db.close_db)
    app.jinja_env.globals.update(csrf_token=sec.csrf_token, has_role=sec.has_role, ROLE_NAMES=sec.ROLE_NAMES,
                                  today_iso=lambda: date.today().isoformat(),
                                  today_text=lambda: date.today().strftime("%a %d %b %Y"))
    app.jinja_env.filters["num"] = lambda n: f"{int(n or 0):,}"

    def db_write(work, success, target):
        """Run a write in one transaction; turn database rule violations into a flash message."""
        try:
            work()
            db.commit()
            flash(success, "success")
            return redirect(target)
        except pymysql.MySQLError as err:
            db.rollback()
            flash(db.friendly_error(err), "danger")
            return None

    # ================================================================ login / logout
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            # Already signed in: say who, so trying another account here doesn't fail silently.
            flash(f"You are already signed in as {g.user['full_name']} ({sec.ROLE_NAMES[g.user['role']]}). "
                  "Log out first to use a different account.", "warning")
            return redirect(url_for("dashboard"))
        error = None
        if session.pop("expired", False):
            error = "Your session expired after 30 minutes of inactivity. Please log in again."
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            if sec.is_locked(username):
                error = (f"Too many failed attempts. Try again in {app.config['LOCKOUT_MINUTES']} minutes.")
                sec.audit("LOGIN_LOCKED", attempted=username[:30])
            elif not v.USERNAME_RE.match(username) or not password or len(password) > 64:
                error = "Invalid username or password."
                sec.record_failure(username)
            else:
                user = db.query("SELECT user_id, username, full_name, role, password_hash FROM app_user "
                                "WHERE username = %s", (username,), one=True)
                if user and check_password_hash(user["password_hash"], password):
                    sec.clear_failures(username)
                    sec.start_session(user)
                    sec.audit("LOGIN_OK")
                    nxt = request.args.get("next", "")
                    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
                sec.record_failure(username)
                sec.audit("LOGIN_FAILED", attempted=username[:30])
                error = "Invalid username or password."
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    def logout():
        sec.audit("LOGOUT")
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("login"))

    # ================================================================ dashboard
    @app.route("/")
    @sec.login_required
    def dashboard():
        counts = db.query("""SELECT
            (SELECT COUNT(*) FROM disaster WHERE status = 'ACTIVE') AS disasters,
            (SELECT COUNT(*) FROM relief_request WHERE status IN ('PENDING','PARTIAL')) AS open_requests,
            (SELECT COUNT(*) FROM v_low_stock) AS low_stock,
            (SELECT COUNT(*) FROM allocation WHERE status = 'DISPATCHED') AS in_transit""", one=True)
        critical = db.query("""SELECT request_id, zone_name, disaster_name, urgency, status, priority_score
                                 FROM v_request_summary WHERE status IN ('PENDING','PARTIAL')
                                ORDER BY priority_score DESC LIMIT 6""")
        low = db.query("SELECT * FROM v_low_stock ORDER BY quantity / reorder_level, reorder_level DESC LIMIT 8")
        unmet = db.query("SELECT * FROM v_unmet_demand WHERE unmet > 0 ORDER BY unmet DESC")
        demand = db.query("""SELECT COALESCE(SUM(requested),0) AS requested, COALESCE(SUM(allocated),0) AS allocated
                               FROM v_unmet_demand""", one=True)
        active = db.query("""SELECT d.disaster_id, d.disaster_name, d.disaster_type, d.start_date,
                                     COUNT(z.zone_id) AS zones, COALESCE(SUM(z.affected_population),0) AS people,
                                     (SELECT COUNT(*) FROM relief_request r JOIN zone rz ON rz.zone_id = r.zone_id
                                       WHERE rz.disaster_id = d.disaster_id
                                         AND r.status IN ('PENDING','PARTIAL')) AS open_requests
                                FROM disaster d LEFT JOIN zone z ON z.disaster_id = d.disaster_id
                               WHERE d.status = 'ACTIVE'
                               GROUP BY d.disaster_id ORDER BY people DESC""")
        return render_template("dashboard.html", counts=counts, critical=critical, low=low, unmet=unmet,
                               demand=demand, active=active, today=date.today())

    # ================================================================ users (admin)
    @app.route("/users", methods=["GET", "POST"])
    @sec.roles_required("ADMIN")
    def users():
        form = v.Form(request.form)
        if request.method == "POST":
            form.text("full_name", "Full name", 2, 80, v.NAME_RE, "Full name may contain only letters, spaces, . ' -")
            form.text("username", "Username", 3, 30, v.USERNAME_RE,
                      "Username: 3–30 lowercase letters, digits, . or _, starting with a letter")
            form.choice("role", "Role", sec.ROLES)
            pw = request.form.get("password", "")
            problems = v.password_problems(pw)
            if problems:
                form.errors["password"] = "Password needs " + ", ".join(problems) + "."
            elif pw != request.form.get("confirm", ""):
                form.errors["confirm"] = "Passwords do not match."
            if form.ok:
                c = form.clean
                done = db_write(lambda: db.execute(
                    "INSERT INTO app_user (full_name, username, password_hash, role) VALUES (%s, %s, %s, %s)",
                    (c["full_name"], c["username"].lower(), generate_password_hash(pw, method=HASH_METHOD), c["role"])),
                    f"User {c['username']} created.", url_for("users"))
                if done:
                    sec.audit("USER_CREATED", new_user=c["username"])
                    return done
        rows = db.query("SELECT user_id, full_name, username, role FROM app_user ORDER BY user_id")
        return render_template("users.html", form=form, rows=rows, roles=sec.ROLES)

    # ================================================================ disasters and zones
    @app.route("/disasters", methods=["GET", "POST"])
    @sec.roles_required("ADMIN", "COORDINATOR")
    def disasters():
        dform, zform = v.Form({}), v.Form({})
        if request.method == "POST" and request.form.get("form") == "disaster":
            dform = v.Form(request.form)
            dform.text("disaster_name", "Disaster name", 3, 100, v.PLACE_RE)
            dform.choice("disaster_type", "Disaster type", DISASTER_TYPES)
            dform.date("start_date", "Start date", oldest_days=365)
            if dform.ok:
                c = dform.clean
                done = db_write(lambda: db.execute(
                    "INSERT INTO disaster (disaster_name, disaster_type, start_date) VALUES (%s, %s, %s)",
                    (c["disaster_name"], c["disaster_type"], c["start_date"])),
                    f"Disaster “{c['disaster_name']}” registered.", url_for("disasters"))
                if done:
                    return done
        if request.method == "POST" and request.form.get("form") == "zone":
            zform = v.Form(request.form)
            active = [str(r["disaster_id"]) for r in db.query("SELECT disaster_id FROM disaster WHERE status='ACTIVE'")]
            zform.choice("disaster_id", "Disaster", active)
            zform.text("zone_name", "Zone name", 2, 80, v.PLACE_RE)
            zform.text("district", "District", 2, 50, v.NAME_RE, "District may contain only letters and spaces.")
            zform.integer("affected_population", "Affected population", 0, 10_000_000)
            zform.integer("damage_level", "Damage level", 1, 5)
            if zform.ok:
                c = zform.clean
                done = db_write(lambda: db.execute(
                    "INSERT INTO zone (disaster_id, zone_name, district, affected_population, damage_level) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (c["disaster_id"], c["zone_name"], c["district"], c["affected_population"], c["damage_level"])),
                    f"Zone “{c['zone_name']}” added.", url_for("disasters"))
                if done:
                    return done
        rows = db.query("""SELECT d.*, COUNT(z.zone_id) AS zones, COALESCE(SUM(z.affected_population),0) AS people
                             FROM disaster d LEFT JOIN zone z ON z.disaster_id = d.disaster_id
                            GROUP BY d.disaster_id ORDER BY d.status, d.start_date DESC""")
        return render_template("disasters.html", dform=dform, zform=zform, rows=rows, types=DISASTER_TYPES)

    @app.route("/disasters/<int:disaster_id>/close", methods=["POST"])
    @sec.roles_required("ADMIN", "COORDINATOR")
    def close_disaster(disaster_id):
        res = db_write(lambda: db.execute("UPDATE disaster SET status='CLOSED' WHERE disaster_id=%s", (disaster_id,)),
                       "Disaster closed. No new requests will be accepted for it.", url_for("disasters"))
        return res or redirect(url_for("disasters"))

    # ================================================================ donors and donations
    @app.route("/donations", methods=["GET", "POST"])
    @sec.roles_required("ADMIN", "WAREHOUSE_MANAGER")
    def donations():
        dn, df = v.Form({}), v.Form({})
        donors = db.query("SELECT donor_id, donor_name FROM donor ORDER BY donor_name")
        warehouses = db.query("SELECT warehouse_id, warehouse_name FROM warehouse ORDER BY warehouse_name")
        items = db.query("SELECT item_id, item_name, unit FROM item ORDER BY item_name")
        if request.method == "POST" and request.form.get("form") == "donor":
            dn = v.Form(request.form)
            dn.text("donor_name", "Donor name", 2, 100, v.PLACE_RE)
            dn.choice("donor_type", "Donor type", DONOR_TYPES)
            dn.text("phone", "Phone", 1, 10, v.PHONE_RE, "Phone must be 10 digits starting with 6–9.", required=False)
            if dn.ok:
                c = dn.clean
                done = db_write(lambda: db.execute("INSERT INTO donor (donor_name, donor_type, phone) VALUES (%s,%s,%s)",
                                                   (c["donor_name"], c["donor_type"], c["phone"])),
                                f"Donor “{c['donor_name']}” added.", url_for("donations"))
                if done:
                    return done
        if request.method == "POST" and request.form.get("form") == "donation":
            df = v.Form(request.form)
            df.choice("donor_id", "Donor", [d["donor_id"] for d in donors])
            df.choice("warehouse_id", "Warehouse", [w["warehouse_id"] for w in warehouses])
            df.choice("item_id", "Item", [i["item_id"] for i in items])
            df.integer("quantity", "Quantity", 1, 1_000_000)
            df.date("donation_date", "Donation date", oldest_days=365)
            if df.ok:
                c = df.clean
                holder = {}

                def work():
                    holder["id"] = db.execute(
                        "INSERT INTO donation (donor_id, warehouse_id, item_id, quantity, donation_date) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (c["donor_id"], c["warehouse_id"], c["item_id"], c["quantity"], c["donation_date"]))
                done = db_write(work, "Donation recorded and stock updated.", url_for("donations"))
                if done:
                    flash(f"Receipt number: DON-{holder['id']:05d}", "info")
                    return done
        recent = db.query("""SELECT d.donation_id, d.donation_date, dn.donor_name, w.warehouse_name, i.item_name,
                                    d.quantity, i.unit
                               FROM donation d JOIN donor dn USING (donor_id) JOIN warehouse w USING (warehouse_id)
                               JOIN item i USING (item_id) ORDER BY d.donation_id DESC LIMIT 8""")
        return render_template("donations.html", dn=dn, df=df, donors=donors, warehouses=warehouses, items=items,
                               recent=recent, donor_types=DONOR_TYPES)

    # ================================================================ relief requests
    @app.route("/requests/new", methods=["GET", "POST"])
    @sec.roles_required("COORDINATOR", "FIELD_OFFICER")
    def new_request():
        zones = db.query("""SELECT z.zone_id, z.zone_name, z.district, d.disaster_name FROM zone z
                              JOIN disaster d ON d.disaster_id = z.disaster_id
                             WHERE d.status = 'ACTIVE' ORDER BY d.disaster_name, z.zone_name""")
        items = db.query("SELECT item_id, item_name, unit FROM item ORDER BY item_name")
        form, item_errors, rows = v.Form(request.form), [], []
        if request.method == "POST":
            form.choice("zone_id", "Zone", [z["zone_id"] for z in zones])
            form.integer("urgency", "Urgency", 1, 5)
            rows, item_errors = v.request_items(request.form, {str(i["item_id"]) for i in items})
            if form.ok and not item_errors:
                c = form.clean
                holder = {}

                def work():
                    rid = db.execute("INSERT INTO relief_request (zone_id, raised_by, urgency) VALUES (%s,%s,%s)",
                                     (c["zone_id"], g.user["user_id"], c["urgency"]))
                    for item_id, qty in rows:
                        db.execute("INSERT INTO request_item (request_id, item_id, qty_requested) VALUES (%s,%s,%s)",
                                   (rid, item_id, qty))
                    holder["id"] = rid
                done = db_write(work, "Relief request submitted.", url_for("requests_list"))
                if done:
                    flash(f"Request number: {holder['id']}", "info")
                    return done
        submitted = list(zip(request.form.getlist("item_id"), request.form.getlist("qty"))) or [("", "")]
        return render_template("request_new.html", form=form, zones=zones, items=items,
                               item_errors=item_errors, submitted=submitted)

    @app.route("/requests")
    @sec.login_required
    def requests_list():
        status = request.args.get("status", "")
        q = request.args.get("q", "").strip()[:80]
        sql = "SELECT * FROM v_request_summary WHERE 1=1"
        args = []
        if status in STATUSES:
            sql += " AND status = %s"
            args.append(status)
        if q:
            sql += " AND (zone_name LIKE %s OR disaster_name LIKE %s)"
            args += [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY FIELD(status,'PENDING','PARTIAL','ALLOCATED','DELIVERED','CANCELLED'), priority_score DESC"
        tabs = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) AS n FROM relief_request GROUP BY status")}
        return render_template("requests.html", rows=db.query(sql, args), status=status if status in STATUSES else "",
                               q=q, statuses=STATUSES, tabs=tabs)

    @app.route("/requests/<int:request_id>/cancel", methods=["POST"])
    @sec.roles_required("COORDINATOR")
    def cancel_request(request_id):
        res = db_write(lambda: db.callproc("sp_cancel_request", (request_id,)),
                       f"Request {request_id} cancelled; its reserved stock was returned.", url_for("requests_list"))
        return res or redirect(url_for("requests_list"))

    # ================================================================ allocation
    @app.route("/allocation")
    @sec.roles_required("COORDINATOR")
    def allocation():
        pending = db.query("""SELECT request_id, zone_name, disaster_name, urgency, status, priority_score,
                                     requested, allocated FROM v_request_summary
                               WHERE status IN ('PENDING','PARTIAL') ORDER BY priority_score DESC""")
        recent = db.query("""SELECT a.allocation_id, a.request_id, z.zone_name, i.item_name, w.warehouse_name,
                                    a.quantity, a.status FROM allocation a
                               JOIN relief_request r ON r.request_id = a.request_id JOIN zone z ON z.zone_id = r.zone_id
                               JOIN item i ON i.item_id = a.item_id JOIN warehouse w ON w.warehouse_id = a.warehouse_id
                              ORDER BY a.allocation_id DESC LIMIT 12""")
        unmet = db.query("SELECT * FROM v_unmet_demand WHERE unmet > 0")
        return render_template("allocation.html", pending=pending, recent=recent, unmet=unmet)

    @app.route("/allocation/run", methods=["POST"])
    @sec.roles_required("COORDINATOR")
    def run_allocation():
        before = db.query("SELECT COALESCE(MAX(allocation_id),0) AS m FROM allocation", one=True)["m"]
        try:
            db.callproc("sp_allocate_pending")
            db.commit()
            made = db.query("SELECT COUNT(*) AS n FROM allocation WHERE allocation_id > %s", (before,), one=True)["n"]
            sec.audit("ALLOCATION_RUN", allocations=made)
            flash(f"Allocation finished: {made} new allocation(s) made in priority order.", "success")
        except pymysql.MySQLError as err:
            db.rollback()
            flash(db.friendly_error(err), "danger")
        return redirect(url_for("allocation"))

    # ================================================================ dispatch and delivery
    @app.route("/dispatch", methods=["GET", "POST"])
    @sec.roles_required("COORDINATOR", "WAREHOUSE_MANAGER", "FIELD_OFFICER")
    def dispatch():
        if request.method == "POST":
            role = g.user["role"]
            target = {"WAREHOUSE_MANAGER": ("ALLOCATED", "DISPATCHED"),
                      "FIELD_OFFICER": ("DISPATCHED", "DELIVERED")}.get(role)
            ids = [i for i in request.form.getlist("allocation_id") if i.isdigit()]
            if not target:
                flash("Your role can view dispatches but not change them.", "warning")
            elif not ids:
                flash("Select at least one allocation.", "warning")
            else:
                frm, to = target

                def work():
                    for i in ids:
                        db.execute("UPDATE allocation SET status=%s WHERE allocation_id=%s AND status=%s", (to, int(i), frm))
                done = db_write(work, f"{len(ids)} allocation(s) marked {to}.", url_for("dispatch"))
                if done:
                    return done
        rows = db.query("""SELECT a.allocation_id, a.request_id, z.zone_name, i.item_name, i.unit, w.warehouse_name,
                                  a.quantity, a.status, a.allocated_on FROM allocation a
                             JOIN relief_request r ON r.request_id = a.request_id JOIN zone z ON z.zone_id = r.zone_id
                             JOIN item i ON i.item_id = a.item_id JOIN warehouse w ON w.warehouse_id = a.warehouse_id
                            WHERE a.status IN ('ALLOCATED','DISPATCHED')
                            ORDER BY FIELD(a.status,'ALLOCATED','DISPATCHED'), a.allocation_id""")
        stages = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) AS n FROM allocation GROUP BY status")}
        return render_template("dispatch.html", rows=rows, stages=stages)

    # ================================================================ inventory
    @app.route("/inventory", methods=["GET", "POST"])
    @sec.login_required
    def inventory():
        form = v.Form({})
        if request.method == "POST":
            if not sec.has_role("ADMIN", "WAREHOUSE_MANAGER"):
                return render_template("error.html", code=403), 403
            form = v.Form(request.form)
            pairs = [f"{r['warehouse_id']}-{r['item_id']}" for r in db.query("SELECT warehouse_id, item_id FROM inventory")]
            form.choice("pair", "Stock item", pairs)
            form.integer("reorder_level", "Reorder level", 0, 1_000_000)
            if form.ok:
                wh, it = form.clean["pair"].split("-")
                done = db_write(lambda: db.execute(
                    "UPDATE inventory SET reorder_level=%s WHERE warehouse_id=%s AND item_id=%s",
                    (form.clean["reorder_level"], int(wh), int(it))), "Reorder level updated.", url_for("inventory"))
                if done:
                    return done
        rows = db.query("""SELECT inv.warehouse_id, inv.item_id, w.warehouse_name, w.district, i.item_name, i.unit, inv.quantity,
                                  inv.reorder_level, IF(inv.quantity < inv.reorder_level,'REORDER','OK') AS stock_status
                             FROM inventory inv JOIN warehouse w USING (warehouse_id) JOIN item i USING (item_id)
                            ORDER BY w.warehouse_name, i.item_name""")
        return render_template("inventory.html", rows=rows, form=form)

    # ================================================================ errors
    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(500)
    def error_page(err):
        code = getattr(err, "code", 500)
        return render_template("error.html", code=code), code

    # MySQL is not running, or the app cannot log in to it: say so instead of a generic 500.
    DB_DOWN = {1045, 1049, 2002, 2003, 2006, 2013}   # access denied, unknown database, cannot connect, connection lost

    @app.errorhandler(pymysql.err.OperationalError)
    def database_down(err):
        code = err.args[0] if err.args else None
        if code not in DB_DOWN:
            return render_template("error.html", code=500), 500
        sec.audit("DB_UNAVAILABLE", mysql_error=code)
        return render_template("error.html", code=503), 503

    return app


app = create_app()

if __name__ == "__main__":
    import os
    # Listen on the local network only; never run with debug=True in use.
    app.run(host=os.environ.get("DRAIMS_HOST", "0.0.0.0"), port=int(os.environ.get("DRAIMS_PORT", "8000")), debug=False)
