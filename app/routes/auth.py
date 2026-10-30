from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .. import models, reports
from ..database import get_db
from ..utils import login_required

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = models.authenticate(get_db(), request.form.get("username"),
                                   request.form.get("password"))
        if user:
            session.clear()
            session.update(user_id=user["user_id"], username=user["username"],
                           role=user["role"])
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//")
                            else url_for("auth.dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/")
@login_required
def dashboard():
    db = get_db()
    if session["role"] == "admin":
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=29)).isoformat()
        return render_template(
            "dashboard_admin.html", k=reports.kpis(db, start, end), start=start, end=end,
            low=reports.low_stock(db).head(8).to_dict("records"),
            exp=reports.expiring(db).head(8).to_dict("records"),
            recent=models.recent_sales(db, limit=8))
    return render_template("dashboard_cashier.html",
                           recent=models.recent_sales(db, session["user_id"], 8))
