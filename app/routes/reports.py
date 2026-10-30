from datetime import date

from flask import Blueprint, Response, flash, render_template, request

from .. import reports as rep
from ..database import get_db
from ..utils import ValidationError, admin_required, date_range

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _range():
    try:
        return date_range(request.args.get("start"), request.args.get("end"))
    except ValidationError as e:
        flash(str(e), "error")
        return date_range(None, None)


@bp.route("/")
@admin_required
def index():
    db = get_db()
    start, end = _range()
    metric = "quantity" if request.args.get("metric") == "quantity" else "revenue"
    return render_template(
        "reports.html", start=start, end=end, metric=metric, k=rep.kpis(db, start, end),
        daily=rep.daily_sales(db, start, end).to_dict("records"),
        monthly=rep.monthly_sales(db).to_dict("records"),
        top=rep.top_products(db, start, end, 10, metric).to_dict("records"),
        cats=rep.category_share(db, start, end).to_dict("records"),
        slow=rep.slow_moving(db).head(15).to_dict("records"),
        low=rep.low_stock(db).to_dict("records"),
        exp=rep.expiring(db).to_dict("records"),
        forecast=rep.forecast_next_7_days(db).to_dict("records"))


@bp.route("/chart/<kind>.png")
@admin_required
def chart(kind):
    start, end = _range()
    metric = "quantity" if request.args.get("metric") == "quantity" else "revenue"
    return Response(rep.chart(get_db(), kind, start, end, metric), mimetype="image/png")


@bp.route("/export/<name>.csv")
@admin_required
def export(name):
    db = get_db()
    start, end = _range()
    builders = {
        "daily": lambda: rep.daily_sales(db, start, end),
        "monthly": lambda: rep.monthly_sales(db),
        "top": lambda: rep.top_products(db, start, end, 10),
        "category": lambda: rep.category_share(db, start, end),
        "low_stock": lambda: rep.low_stock(db),
        "expiry": lambda: rep.expiring(db),
        "slow_moving": lambda: rep.slow_moving(db),
    }
    if name not in builders:
        flash("Unknown report.", "error")
        return Response("Unknown report", status=404)
    return Response(builders[name]().to_csv(index=False), mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename={name}_report_{date.today()}.csv"})
