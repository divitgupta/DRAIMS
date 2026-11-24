"""Server-side validation. Every form is checked here before anything reaches the database,
even though the browser checks it too (browser checks can be bypassed)."""
import re
from datetime import date, datetime, timedelta

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]*$")
PLACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'()\-/]*$")
USERNAME_RE = re.compile(r"^[a-z][a-z0-9._]{2,29}$")
PHONE_RE = re.compile(r"^[6-9][0-9]{9}$")


class Form:
    def __init__(self, data):
        self.data = data
        self.errors = {}
        self.clean = {}

    @property
    def ok(self):
        return not self.errors

    def _raw(self, name):
        return (self.data.get(name) or "").strip()

    def text(self, name, label, min_len=1, max_len=100, regex=None, regex_msg=None, required=True):
        v = self._raw(name)
        if not v:
            if required:
                self.errors[name] = f"{label} is required."
            self.clean[name] = None
            return None
        if len(v) < min_len or len(v) > max_len:
            self.errors[name] = f"{label} must be {min_len}–{max_len} characters."
        elif regex and not regex.match(v):
            self.errors[name] = regex_msg or f"{label} contains characters that are not allowed."
        self.clean[name] = v
        return v

    def integer(self, name, label, lo, hi, required=True):
        v = self._raw(name)
        if not v:
            if required:
                self.errors[name] = f"{label} is required."
            return None
        if not re.fullmatch(r"-?\d+", v):
            self.errors[name] = f"{label} must be a whole number."
            return None
        n = int(v)
        if n < lo or n > hi:
            self.errors[name] = f"{label} must be between {lo:,} and {hi:,}."
        self.clean[name] = n
        return n

    def choice(self, name, label, choices):
        v = self._raw(name)
        allowed = {str(c) for c in choices}
        if v not in allowed:
            self.errors[name] = f"Please choose a valid {label.lower()}."
            return None
        self.clean[name] = v
        return v

    def date(self, name, label, oldest_days=None, allow_future=False):
        v = self._raw(name)
        if not v:
            self.errors[name] = f"{label} is required."
            return None
        try:
            d = datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            self.errors[name] = f"{label} is not a valid date."
            return None
        if not allow_future and d > date.today():
            self.errors[name] = f"{label} cannot be in the future."
        elif oldest_days and d < date.today() - timedelta(days=oldest_days):
            self.errors[name] = f"{label} cannot be more than {oldest_days} days ago."
        self.clean[name] = d
        return d


def password_problems(pw):
    problems = []
    if len(pw) < 8 or len(pw) > 64:
        problems.append("8–64 characters")
    if not re.search(r"[A-Z]", pw):
        problems.append("an uppercase letter")
    if not re.search(r"[a-z]", pw):
        problems.append("a lowercase letter")
    if not re.search(r"\d", pw):
        problems.append("a digit")
    if not re.search(r"[^A-Za-z0-9]", pw):
        problems.append("a special character")
    return problems


def request_items(form_data, valid_item_ids):
    """Validate the repeating item rows of the relief request form."""
    item_ids = form_data.getlist("item_id")
    qtys = form_data.getlist("qty")
    rows, errors, seen = [], [], set()
    for i, (it, q) in enumerate(zip(item_ids, qtys), start=1):
        it, q = it.strip(), q.strip()
        if not it and not q:
            continue
        if it not in valid_item_ids:
            errors.append(f"Row {i}: choose an item.")
            continue
        if it in seen:
            errors.append(f"Row {i}: this item is already in the request.")
            continue
        if not re.fullmatch(r"\d+", q) or not 1 <= int(q) <= 100000:
            errors.append(f"Row {i}: quantity must be a whole number from 1 to 100,000.")
            continue
        seen.add(it)
        rows.append((int(it), int(q)))
    if not rows and not errors:
        errors.append("Add at least one item.")
    if len(item_ids) > 15:
        errors.append("A request can have at most 15 items.")
    return rows, errors
