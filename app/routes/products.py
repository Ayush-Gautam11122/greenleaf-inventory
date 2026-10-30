from flask import (Blueprint, Response, flash, redirect, render_template, request,
                   url_for)

from .. import models
from ..database import get_db
from ..utils import ValidationError, admin_required

bp = Blueprint("products", __name__, url_prefix="/products")


@bp.route("/")
@admin_required
def index():
    db = get_db()
    q, cat, status = (request.args.get(k, "").strip() for k in ("q", "category", "status"))
    return render_template("products.html", products=models.search_products(db, q, cat, status),
                           categories=models.categories(db), q=q, cat=cat, status=status)


def _form(product=None):
    return render_template("product_form.html", product=product,
                           suppliers=models.list_suppliers(get_db()),
                           categories=models.categories(get_db()))


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    if request.method == "POST":
        try:
            models.add_product(get_db(), models.validate_product(request.form))
            flash("Product added.", "success")
            return redirect(url_for("products.index"))
        except ValidationError as e:
            flash(str(e), "error")
        return render_template("product_form.html", product=request.form,
                               suppliers=models.list_suppliers(get_db()),
                               categories=models.categories(get_db()))
    return _form()


@bp.route("/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def edit(pid):
    db = get_db()
    product = models.get_product(db, pid)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("products.index"))
    if request.method == "POST":
        try:
            models.update_product(db, pid, models.validate_product(request.form))
            flash("Product updated.", "success")
            return redirect(url_for("products.index"))
        except ValidationError as e:
            flash(str(e), "error")
        return render_template("product_form.html", product={**request.form, "product_id": pid},
                               suppliers=models.list_suppliers(db),
                               categories=models.categories(db))
    return _form(product)


@bp.route("/<int:pid>/delete", methods=["POST"])
@admin_required
def delete(pid):
    if models.delete_product(get_db(), pid):
        flash("Product deleted.", "success")
    else:
        flash("This product appears on past bills and can't be deleted. "
              "Set its stock to 0 instead.", "error")
    return redirect(url_for("products.index"))


@bp.route("/import", methods=["GET", "POST"])
@admin_required
def import_csv():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose a CSV file first.", "error")
        else:
            try:
                text = f.read().decode("utf-8-sig")
                added, updated, errors = models.import_products_csv(get_db(), text)
                flash(f"Imported: {added} added, {updated} updated, {len(errors)} skipped.",
                      "success" if not errors else "warning")
                return render_template("import.html", errors=errors)
            except UnicodeDecodeError:
                flash("Could not read the file – please upload a UTF-8 CSV.", "error")
            except ValidationError as e:
                flash(str(e), "error")
    return render_template("import.html", errors=[])


@bp.route("/template.csv")
@admin_required
def template():
    body = ",".join(models.CSV_COLUMNS) + "\nBasmati Rice 5kg,Grains,540,40,10,,Fresh Farms\n"
    return Response(body, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=products_template.csv"})


@bp.route("/export.csv")
@admin_required
def export():
    import pandas as pd
    df = pd.read_sql_query(
        "SELECT p.name,p.category,p.unit_price,p.stock_qty,p.reorder_level,p.expiry_date,"
        "s.name AS supplier FROM products p LEFT JOIN suppliers s USING(supplier_id) ORDER BY p.name",
        get_db())
    return Response(df.to_csv(index=False), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=products.csv"})


@bp.route("/suppliers", methods=["GET", "POST"])
@admin_required
def suppliers():
    db = get_db()
    if request.method == "POST":
        try:
            models.add_supplier(db, request.form.get("name"), request.form.get("phone"),
                                request.form.get("email"))
            flash("Supplier added.", "success")
        except ValidationError as e:
            flash(str(e), "error")
        return redirect(url_for("products.suppliers"))
    return render_template("suppliers.html", suppliers=models.list_suppliers(db))


@bp.route("/suppliers/<int:sid>/delete", methods=["POST"])
@admin_required
def supplier_delete(sid):
    models.delete_supplier(get_db(), sid)
    flash("Supplier removed.", "success")
    return redirect(url_for("products.suppliers"))
