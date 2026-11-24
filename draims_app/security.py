"""Authentication, role checks, CSRF protection, login throttling and security headers."""
import hmac
import logging
import os
import secrets
import time
from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for

ROLES = ("ADMIN", "COORDINATOR", "WAREHOUSE_MANAGER", "FIELD_OFFICER")
ROLE_NAMES = {"ADMIN": "Administrator", "COORDINATOR": "Relief Coordinator",
              "WAREHOUSE_MANAGER": "Warehouse Manager", "FIELD_OFFICER": "Field Officer"}

# ---------------------------------------------------------------- audit log
_log = logging.getLogger("draims.security")


def setup_audit_log(base_dir):
    os.makedirs(os.path.join(base_dir, "logs"), exist_ok=True)
    handler = logging.FileHandler(os.path.join(base_dir, "logs", "security.log"))
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _log.addHandler(handler)
    _log.setLevel(logging.INFO)


def audit(event, **fields):
    who = session.get("username", "-")
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    _log.info(f"{event} user={who} ip={request.remote_addr} {extra}".strip())


# ---------------------------------------------------------------- login throttling
_failures = {}   # key -> list of failure timestamps (kept in memory; resets on restart)


def _key(username):
    return f"{(username or '').lower()}|{request.remote_addr}"


def is_locked(username):
    cfg = current_app.config
    window = cfg["LOCKOUT_MINUTES"] * 60
    recent = [t for t in _failures.get(_key(username), []) if time.time() - t < window]
    _failures[_key(username)] = recent
    return len(recent) >= cfg["MAX_FAILED_LOGINS"]


def record_failure(username):
    _failures.setdefault(_key(username), []).append(time.time())


def clear_failures(username):
    _failures.pop(_key(username), None)


# ---------------------------------------------------------------- sessions and roles
def start_session(user):
    session.clear()                      # new session on every login (prevents session fixation)
    session.permanent = True
    session["user_id"] = user["user_id"]
    session["username"] = user["username"]
    session["full_name"] = user["full_name"]
    session["role"] = user["role"]
    session["csrf"] = secrets.token_urlsafe(32)
    session["seen"] = int(time.time())


def load_user():
    """Runs before every request: enforce the idle timeout and expose the user to templates."""
    g.user = None
    if "user_id" in session:
        idle = current_app.config["PERMANENT_SESSION_LIFETIME"].total_seconds()
        if time.time() - session.get("seen", 0) > idle:
            session.clear()
            session["expired"] = True          # shown once on the login page
            return
        session["seen"] = int(time.time())
        g.user = {k: session[k] for k in ("user_id", "username", "full_name", "role")}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                audit("ACCESS_DENIED", path=request.path)
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def has_role(*roles):
    return g.user is not None and g.user["role"] in roles


# ---------------------------------------------------------------- CSRF
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    """Runs before every request: every POST must carry the token stored in the session."""
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            audit("CSRF_REJECTED", path=request.path)
            abort(400)


# ---------------------------------------------------------------- headers
def security_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if g.get("user"):
        resp.headers["Cache-Control"] = "no-store"
    return resp
