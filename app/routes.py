"""HTTP routes (single blueprint): auth, dashboard, products, billing, reports."""
import io
from datetime import date

import pandas as pd
from flask import (Blueprint, Response, flash, redirect, render_template, request,
                   session, url_for)

from . import models, reports
from .database import get_db
from .utils import (ValidationError, login_required, parse_date, parse_float,
                    parse_int, role_required)

bp = Blueprint("main", __name__)


def csv_response(df, filename):
    return Response(
        df.to_csv(index=False),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------


@bp.route("/")
def index():
    return redirect(url_for("main.dashboard" if "user_id" in session else "main.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = models.authenticate(get_db(), request.form.get("username"), request.form.get("password"))
        if user is None:
            flash("Invalid username or password.", "error")
        else:
            session.clear()
            session.update(user_id=user["user_id"], username=user["username"], role=user["role"])
            return redirect(url_for("main.dashboard"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))


# ----------------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------------


@bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    ctx = {}
    if session["role"] == "admin":
        start, end = reports.default_range()
        sales, items = reports.load(db, start, end)
        daily = reports.daily_revenue(sales, items)
        ctx.update(
            kpi=reports.kpis(db, start, end), start=start, end=end,
            low=reports.low_stock(db).head(6).to_dict("records"),
            expiring=reports.expiring(db).head(6).to_dict("records"),
            chart=reports.chart_trend(daily, "date", "revenue", "Revenue – last 30 days"),
        )
    else:
        today = date.today().isoformat()
        row = db.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(total_amount), 0) AS t FROM sales "
            "WHERE user_id = ? AND sale_date = ?", (session["user_id"], today)).fetchone()
        ctx.update(today_bills=row["n"], today_total=row["t"])
    return render_template("dashboard.html", **ctx)


# ----------------------------------------------------------------------------
# Products (admin)
# ----------------------------------------------------------------------------


@bp.route("/products")
@role_required("admin")
def products():
    db = get_db()
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    status = request.args.get("status", "all")
    rows = models.search_products(db, q, category, status)
    return render_template(
        "products.html", products=rows, categories=models.list_categories(db),
        q=q, category=category, status=status, today=date.today().isoformat(),
        soon=date.fromordinal(date.today().toordinal() + 15).isoformat(),
    )


def _product_form(product=None, form=None):
    return render_template(
        "product_form.html", product=product, form=form or product or {},
        suppliers=models.list_suppliers(get_db()), categories=models.list_categories(get_db()),
    )


@bp.route("/products/new", methods=["GET", "POST"])
@role_required("admin")
def product_new():
    if request.method == "POST":
        try:
            models.add_product(get_db(), request.form)
            flash("Product added.", "success")
            return redirect(url_for("main.products"))
        except ValidationError as exc:
            flash(str(exc), "error")
        return _product_form(form=request.form)
    return _product_form()


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def product_edit(product_id):
    product = models.get_product(get_db(), product_id)
    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("main.products"))
    if request.method == "POST":
        try:
            models.update_product(get_db(), product_id, request.form)
            flash("Product updated.", "success")
            return redirect(url_for("main.products"))
        except ValidationError as exc:
            flash(str(exc), "error")
        return _product_form(product=product, form=request.form)
    return _product_form(product=product)


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@role_required("admin")
def product_delete(product_id):
    try:
        models.delete_product(get_db(), product_id)
        flash("Product deleted.", "success")
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.products"))


@bp.route("/products/import", methods=["POST"])
@role_required("admin")
def products_import():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("main.products"))
    try:
        text = file.read().decode("utf-8-sig")
        added, errors = models.import_products_csv(get_db(), text)
        flash(f"Imported {added} product(s).", "success" if added else "warning")
        for err in errors[:10]:
            flash(err, "error")
        if len(errors) > 10:
            flash(f"...and {len(errors) - 10} more rows were skipped.", "error")
    except UnicodeDecodeError:
        flash("That file is not a valid UTF-8 CSV.", "error")
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.products"))


@bp.route("/products/export")
@role_required("admin")
def products_export():
    df = pd.read_sql_query(
        "SELECT name, category, unit_price, stock_qty, reorder_level, expiry_date "
        "FROM products ORDER BY name", get_db())
    return csv_response(df, "products.csv")


# ----------------------------------------------------------------------------
# Billing
# ----------------------------------------------------------------------------


@bp.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    db = get_db()
    prefill = {"lines": [], "discount": 0}
    if request.method == "POST":
        ids = request.form.getlist("product_id")
        qtys = request.form.getlist("quantity")
        prefill = {
            "lines": [{"product_id": i, "quantity": q} for i, q in zip(ids, qtys) if i],
            "discount": request.form.get("discount_pct", 0),
        }
        try:
            items = [(parse_int(i, "Product", 1), parse_int(q, "Quantity", 1))
                     for i, q in zip(ids, qtys) if i]
            sale_id = models.create_bill(db, session["user_id"], items,
                                         request.form.get("discount_pct") or 0)
            flash("Bill created and stock updated.", "success")
            return redirect(url_for("main.bill", sale_id=sale_id))
        except ValidationError as exc:
            flash(str(exc), "error")
    today = date.today().isoformat()
    rows = db.execute(
        "SELECT product_id, name, unit_price, stock_qty FROM products "
        "WHERE stock_qty > 0 AND (expiry_date IS NULL OR expiry_date >= ?) ORDER BY name",
        (today,)).fetchall()
    products = [{"id": r["product_id"], "name": r["name"], "price": r["unit_price"],
                 "stock": r["stock_qty"]} for r in rows]
    return render_template("billing.html", products=products, prefill=prefill)


def _load_bill_or_none(sale_id):
    sale, items = models.get_bill(get_db(), sale_id)
    if sale is None or (session["role"] != "admin" and sale["user_id"] != session["user_id"]):
        return None, []
    return sale, items


@bp.route("/bills")
@login_required
def bills():
    uid = None if session["role"] == "admin" else session["user_id"]
    return render_template("bills.html", bills=models.recent_bills(get_db(), uid))


@bp.route("/bill/<int:sale_id>")
@login_required
def bill(sale_id):
    sale, items = _load_bill_or_none(sale_id)
    if sale is None:
        flash("Bill not found.", "error")
        return redirect(url_for("main.bills"))
    return render_template("bill.html", sale=sale, items=items)


@bp.route("/bill/<int:sale_id>.csv")
@login_required
def bill_csv(sale_id):
    sale, items = _load_bill_or_none(sale_id)
    if sale is None:
        flash("Bill not found.", "error")
        return redirect(url_for("main.bills"))
    df = pd.DataFrame([{"product": i["name"], "quantity": i["quantity"],
                        "price": i["price"], "line_total": i["line_total"]} for i in items])
    df.loc[len(df)] = ["Subtotal", "", "", sale["subtotal"]]
    df.loc[len(df)] = ["Discount", "", "", -sale["discount"]]
    df.loc[len(df)] = ["TOTAL", "", "", sale["total_amount"]]
    return csv_response(df, f"bill_{sale_id}.csv")


@bp.route("/bill/<int:sale_id>.pdf")
@login_required
def bill_pdf(sale_id):
    sale, items = _load_bill_or_none(sale_id)
    if sale is None:
        flash("Bill not found.", "error")
        return redirect(url_for("main.bills"))
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    w, h = A5
    y = h - 40
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, "GreenLeaf Grocers")
    y -= 18
    c.setFont("Helvetica", 9)
    c.drawString(40, y, f"Bill #{sale['sale_id']}   {sale['sale_date']} {sale['sale_time']}   Cashier: {sale['username']}")
    y -= 24
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((40, "Item"), (240, "Qty"), (280, "Price"), (340, "Total")):
        c.drawString(x, y, t)
    y -= 12
    c.setFont("Helvetica", 9)
    for i in items:
        if y < 90:
            c.showPage()
            y = h - 40
            c.setFont("Helvetica", 9)
        c.drawString(40, y, i["name"][:40])
        c.drawString(240, y, str(i["quantity"]))
        c.drawString(280, y, f"Rs {i['price']:.2f}")
        c.drawString(340, y, f"Rs {i['line_total']:.2f}")
        y -= 13
    y -= 8
    c.drawString(280, y, "Subtotal:")
    c.drawString(340, y, f"Rs {sale['subtotal']:.2f}")
    y -= 13
    c.drawString(280, y, "Discount:")
    c.drawString(340, y, f"- Rs {sale['discount']:.2f}")
    y -= 15
    c.setFont("Helvetica-Bold", 11)
    c.drawString(280, y, "TOTAL:")
    c.drawString(340, y, f"Rs {sale['total_amount']:.2f}")
    c.save()
    return Response(buf.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=bill_{sale_id}.pdf"})


# ----------------------------------------------------------------------------
# Reports (admin)
# ----------------------------------------------------------------------------


def _range_from_request():
    start, end = reports.default_range()
    try:
        s = parse_date(request.args.get("start"), "Start date")
        e = parse_date(request.args.get("end"), "End date")
        start, end = s or start, e or end
        if start > end:
            raise ValidationError("Start date must be on or before the end date.")
    except ValidationError as exc:
        flash(str(exc), "error")
        start, end = reports.default_range()
    return start, end


@bp.route("/reports")
@role_required("admin")
def reports_page():
    db = get_db()
    start, end = _range_from_request()
    metric = request.args.get("metric", "revenue")
    if metric not in reports.METRIC_COL:
        metric = "revenue"
    sales, items = reports.load(db, start, end)
    daily = reports.daily_revenue(sales, items)
    monthly = reports.monthly_revenue(sales, items)
    top = reports.top_products(items, 10, metric)
    cats = reports.category_share(items)
    return render_template(
        "reports.html", start=start, end=end, metric=metric,
        kpi=reports.kpis(db, start, end),
        daily=daily.to_dict("records"), monthly=monthly.to_dict("records"),
        top=top.to_dict("records"), cats=cats.to_dict("records"),
        low=reports.low_stock(db).to_dict("records"),
        expiring=reports.expiring(db).to_dict("records"),
        slow=reports.slow_moving(db).head(15).to_dict("records"),
        charts={
            "daily": reports.chart_trend(daily, "date", metric, "Daily trend"),
            "monthly": reports.chart_trend(monthly, "month", metric, "Monthly trend", "bar"),
            "top": reports.chart_top(top, metric),
            "category": reports.chart_category(cats, metric),
        },
    )


@bp.route("/reports/export/<name>")
@role_required("admin")
def reports_export(name):
    db = get_db()
    start, end = _range_from_request()
    sales, items = reports.load(db, start, end)
    builders = {
        "daily": lambda: reports.daily_revenue(sales, items),
        "monthly": lambda: reports.monthly_revenue(sales, items),
        "top": lambda: reports.top_products(items, 10, request.args.get("metric", "revenue")),
        "category": lambda: reports.category_share(items),
        "low_stock": lambda: reports.low_stock(db),
        "expiry": lambda: reports.expiring(db),
        "slow_moving": lambda: reports.slow_moving(db),
    }
    if name not in builders:
        flash("Unknown report.", "error")
        return redirect(url_for("main.reports_page"))
    return csv_response(builders[name](), f"{name}_report_{start}_to_{end}.csv")
