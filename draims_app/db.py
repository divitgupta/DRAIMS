"""Database helpers. Every query uses parameters (%s), never string formatting."""
import pymysql
from flask import current_app, g

# MySQL error codes we turn into friendly messages
FRIENDLY = {
    1062: "This value already exists. Please use a different one.",
    1451: "This record is still in use and cannot be changed.",
    1452: "The form refers to a record that does not exist.",
    3819: "A value is outside the allowed range.",
}


def get_db():
    if "db" not in g:
        cfg = current_app.config
        g.db = pymysql.connect(
            host=cfg["DB_HOST"], port=cfg["DB_PORT"], user=cfg["DB_USER"],
            password=cfg["DB_PASSWORD"], database=cfg["DB_NAME"],
            cursorclass=pymysql.cursors.DictCursor, autocommit=False, charset="utf8mb4",
        )
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=None, one=False):
    with get_db().cursor() as cur:
        cur.execute(sql, args or ())
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=None):
    """Run one statement; the caller commits."""
    with get_db().cursor() as cur:
        cur.execute(sql, args or ())
        return cur.lastrowid


def callproc(name, args=()):
    with get_db().cursor() as cur:
        cur.callproc(name, args)


def commit():
    get_db().commit()


def rollback():
    get_db().rollback()


def friendly_error(err):
    """Turn a MySQL error into a message that is safe to show to the user."""
    code = err.args[0] if err.args else None
    if code == 1644:            # SIGNAL SQLSTATE '45000' raised by our triggers and procedures
        return str(err.args[1])
    return FRIENDLY.get(code, "The database rejected this change. Please check the values and try again.")
