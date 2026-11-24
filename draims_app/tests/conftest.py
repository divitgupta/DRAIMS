"""Test setup: reloads the database from DRAIMS_database.sql, then records every result to tests/results.json."""
import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
SQL_FILE = os.environ.get("DRAIMS_SQL", os.path.join(HERE, "..", "..", "DRAIMS_database.sql"))
MYSQL = os.environ.get("MYSQL_BIN", "/usr/local/mysql/bin/mysql")
RESULTS = []


@pytest.fixture(scope="session")
def app():
    port = os.environ.get("DRAIMS_DB_PORT", "3306")
    user = os.environ.get("DRAIMS_DB_USER", "root")
    pw = os.environ.get("DRAIMS_DB_PASSWORD", "")
    cmd = [MYSQL, "-h127.0.0.1", f"-P{port}", f"-u{user}"] + ([f"-p{pw}"] if pw else [])
    with open(SQL_FILE) as f:
        subprocess.run(cmd, stdin=f, check=True)
    from app import create_app
    return create_app({"TESTING": True})


@pytest.fixture(autouse=True)
def reset_throttle():
    import security
    security._failures.clear()


def token(html):
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


@pytest.fixture
def login(app):
    def _login(username, password="Relief@2026"):
        c = app.test_client()
        t = token(c.get("/login").text)
        r = c.post("/login", data={"csrf_token": t, "username": username, "password": password})
        return c, r
    return _login


def post(client, path, data):
    """Submit a form the way the browser would: fetch the page, take its CSRF token, post."""
    t = token(client.get("/", follow_redirects=True).text)
    return client.post(path, data={"csrf_token": t, **data}, follow_redirects=True)


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        m = re.search(r"test_([A-Z]\d+)_", report.nodeid)
        doc = getattr(report, "doc", "")
        RESULTS.append({"id": m.group(1) if m else report.nodeid, "test": doc, "outcome": report.outcome})


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    rep.doc = (item.function.__doc__ or "").strip()


def pytest_sessionfinish(session, exitstatus):
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(RESULTS, f, indent=1)
