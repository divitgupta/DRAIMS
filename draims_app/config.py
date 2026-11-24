"""Settings. Every value can be overridden with an environment variable."""
import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _secret_key():
    """Read the session-signing key from instance/secret_key, creating it on first run."""
    if os.environ.get("DRAIMS_SECRET_KEY"):
        return os.environ["DRAIMS_SECRET_KEY"]
    path = os.path.join(BASE_DIR, "instance", "secret_key")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    with open(path) as f:
        return f.read().strip()


class Config:
    # Database (MySQL on the same machine; no cloud service is used)
    DB_HOST = os.environ.get("DRAIMS_DB_HOST", "127.0.0.1")
    DB_PORT = int(os.environ.get("DRAIMS_DB_PORT", "3306"))
    DB_USER = os.environ.get("DRAIMS_DB_USER", "draims_app")
    DB_PASSWORD = os.environ.get("DRAIMS_DB_PASSWORD", "")
    DB_NAME = os.environ.get("DRAIMS_DB_NAME", "draims")

    # Sessions
    SECRET_KEY = _secret_key()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Strict"
    SESSION_COOKIE_NAME = "draims_session"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)   # idle timeout
    MAX_CONTENT_LENGTH = 64 * 1024                       # no form needs more than 64 KB

    # Login throttling
    MAX_FAILED_LOGINS = 5
    LOCKOUT_MINUTES = 10
