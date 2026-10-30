"""Validation helpers, auth decorators and small formatting utilities."""
import secrets
from datetime import date, datetime
from functools import wraps

from flask import flash, redirect, session, url_for, abort, request


class ValidationError(ValueError):
    """Raised for bad user input; message is safe to show to the user."""


def parse_int(value, label, minimum=0):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{label} must be a whole number.")
    if n < minimum:
        raise ValidationError(f"{label} cannot be less than {minimum}.")
    return n


def parse_price(value, label="Price"):
    try:
        p = float(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{label} must be a number.")
    if p != p or p in (float("inf"), float("-inf")):
        raise ValidationError(f"{label} must be a valid number.")
    if p < 0:
        raise ValidationError(f"{label} cannot be negative.")
    return round(p, 2)


def parse_date(value, label="Date", required=False):
    """Return an ISO date string, or None if blank and not required."""
    value = (value or "").strip()
    if not value:
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValidationError(f"{label} must be a valid date in YYYY-MM-DD format.")


def parse_discount(value):
    value = (str(value) if value is not None else "").strip() or "0"
    try:
        d = float(value)
    except ValueError:
        raise ValidationError("Discount must be a number between 0 and 100.")
    if not 0 <= d <= 100:
        raise ValidationError("Discount must be between 0% and 100%.")
    return round(d, 2)


def clean_text(value, label, required=True, max_len=100):
    value = (value or "").strip()
    if required and not value:
        raise ValidationError(f"{label} is required.")
    if len(value) > max_len:
        raise ValidationError(f"{label} is too long (max {max_len} characters).")
    return value


def date_range(start, end, default_days=30):
    """Validate a report date range; defaults to the last *default_days* days."""
    from datetime import timedelta
    end = parse_date(end, "End date") or date.today().isoformat()
    start = parse_date(start, "Start date") or (
        date.fromisoformat(end) - timedelta(days=default_days - 1)).isoformat()
    if start > end:
        raise ValidationError("Start date must not be after the end date.")
    return start, end


def money(v):
    return f"₹{v:,.2f}"


# ---- auth ---------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if session.get("role") != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]
