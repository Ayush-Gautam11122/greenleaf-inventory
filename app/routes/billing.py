import io

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request,
                   session, url_for)

from .. import models
from ..database import get_db
from ..utils import ValidationError, login_required

bp = Blueprint("billing", __name__, url_prefix="/billing")


@bp.route("/", methods=["GET", "POST"])
@login_required
def new_bill():
    db = get_db()
    if request.method == "POST":
        items = list(zip(request.form.getlist("product_id"), request.form.getlist("quantity")))
        items = [(p, q) for p, q in items if p]            # ignore blank rows
        try:
            sale_id = models.create_bill(db, session["user_id"], items,
                                         request.form.get("discount"))
            flash("Bill created and stock updated.", "success")
            return redirect(url_for("billing.receipt", sale_id=sale_id))
        except ValidationError as e:
            flash(str(e), "error")
    prods = [dict(p) for p in db.execute(
        "SELECT product_id,name,category,unit_price,stock_qty FROM products "
        "WHERE stock_qty>0 ORDER BY name")]
    return render_template("billing.html", products=prods)


@bp.route("/receipt/<int:sale_id>")
@login_required
def receipt(sale_id):
    sale, items = _own_sale(sale_id)
    return render_template("receipt.html", sale=sale, items=items)


def _own_sale(sale_id):
    sale, items = models.get_sale(get_db(), sale_id)
    if not sale:
        abort(404)
    if session["role"] != "admin" and sale["user_id"] != session["user_id"]:
        abort(403)
    return sale, items


@bp.route("/receipt/<int:sale_id>.csv")
@login_required
def receipt_csv(sale_id):
    import csv
    sale, items = _own_sale(sale_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["GreenLeaf Grocers", f"Bill #{sale['sale_id']}", sale["sale_date"], sale["sale_time"]])
    w.writerow(["Item", "Qty", "Unit price", "Line total"])
    for i in items:
        w.writerow([i["name"], i["quantity"], f"{i['price']:.2f}", f"{i['line_total']:.2f}"])
    w.writerow([]); w.writerow(["Subtotal", "", "", f"{sale['subtotal']:.2f}"])
    w.writerow([f"Discount {sale['discount_pct']:g}%", "", "",
                f"-{sale['subtotal'] - sale['total_amount']:.2f}"])
    w.writerow(["TOTAL", "", "", f"{sale['total_amount']:.2f}"])
    return Response(buf.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename=bill_{sale_id}.csv"})


@bp.route("/receipt/<int:sale_id>.pdf")
@login_required
def receipt_pdf(sale_id):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    sale, items = _own_sale(sale_id)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A5, title=f"Bill {sale_id}")
    st = getSampleStyleSheet()
    rows = [["Item", "Qty", "Price", "Total"]] + [
        [i["name"], i["quantity"], f"Rs {i['price']:.2f}", f"Rs {i['line_total']:.2f}"] for i in items]
    rows += [["", "", "Subtotal", f"Rs {sale['subtotal']:.2f}"],
             ["", "", f"Discount {sale['discount_pct']:g}%",
              f"-Rs {sale['subtotal'] - sale['total_amount']:.2f}"],
             ["", "", "TOTAL", f"Rs {sale['total_amount']:.2f}"]]
    t = Table(rows, colWidths=[170, 35, 70, 70])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f7d4f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, len(items)), 0.25, colors.grey),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    doc.build([Paragraph("GreenLeaf Grocers", st["Title"]),
               Paragraph(f"Bill #{sale['sale_id']} &nbsp; {sale['sale_date']} {sale['sale_time']}"
                         f" &nbsp; Cashier: {sale['username']}", st["Normal"]),
               Spacer(1, 12), t, Spacer(1, 14),
               Paragraph("Thank you for shopping with us!", st["Italic"])])
    return Response(buf.getvalue(), mimetype="application/pdf", headers={
        "Content-Disposition": f"inline; filename=bill_{sale_id}.pdf"})
