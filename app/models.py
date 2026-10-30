"""Data-access layer: users, suppliers, products and billing."""
import csv
import io
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from .utils import (ValidationError, clean_text, parse_date, parse_discount,
                    parse_int, parse_price)


# ---- users --------------------------------------------------------------
def create_user(db, username, password, role):
    username = clean_text(username, "Username", max_len=40)
    if role not in ("admin", "cashier"):
        raise ValidationError("Role must be admin or cashier.")
    if len(password or "") < 6:
        raise ValidationError("Password must be at least 6 characters.")
    try:
        cur = db.execute(
            "INSERT INTO users(username,password_hash,role) VALUES (?,?,?)",
            (username, generate_password_hash(password), role))
        db.commit()
    except Exception as e:  # sqlite3.IntegrityError
        if "UNIQUE" in str(e):
            raise ValidationError("That username already exists.")
        raise
    return cur.lastrowid


def authenticate(db, username, password):
    row = db.execute("SELECT * FROM users WHERE username = ?",
                     ((username or "").strip(),)).fetchone()
    if row and check_password_hash(row["password_hash"], password or ""):
        return row
    return None


# ---- suppliers ----------------------------------------------------------
def list_suppliers(db):
    return db.execute("SELECT * FROM suppliers ORDER BY name").fetchall()


def add_supplier(db, name, phone, email):
    name = clean_text(name, "Supplier name")
    email = clean_text(email, "Email", required=False)
    if email and "@" not in email:
        raise ValidationError("Email address looks invalid.")
    try:
        db.execute("INSERT INTO suppliers(name,phone,email) VALUES (?,?,?)",
                   (name, clean_text(phone, "Phone", False, 20), email))
        db.commit()
    except Exception as e:
        if "UNIQUE" in str(e):
            raise ValidationError("A supplier with that name already exists.")
        raise


def delete_supplier(db, supplier_id):
    db.execute("DELETE FROM suppliers WHERE supplier_id=?", (supplier_id,))
    db.commit()


# ---- products -----------------------------------------------------------
def validate_product(form):
    """Turn raw form/CSV data into a clean dict, or raise ValidationError."""
    sup = (form.get("supplier_id") or "").strip()
    return {
        "name": clean_text(form.get("name"), "Product name"),
        "category": clean_text(form.get("category"), "Category", max_len=50),
        "unit_price": parse_price(form.get("unit_price"), "Unit price"),
        "stock_qty": parse_int(form.get("stock_qty"), "Stock quantity"),
        "reorder_level": parse_int(form.get("reorder_level") or 10, "Reorder level"),
        "expiry_date": parse_date(form.get("expiry_date"), "Expiry date"),
        "supplier_id": int(sup) if sup.isdigit() else None,
    }


def get_product(db, product_id):
    return db.execute("SELECT p.*, s.name AS supplier FROM products p "
                      "LEFT JOIN suppliers s USING(supplier_id) WHERE product_id=?",
                      (product_id,)).fetchone()


def search_products(db, q="", category="", status=""):
    sql = ("SELECT p.*, s.name AS supplier FROM products p "
           "LEFT JOIN suppliers s USING(supplier_id) WHERE 1=1")
    args = []
    if q:
        sql += " AND (p.name LIKE ? OR p.category LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if category:
        sql += " AND p.category = ?"
        args.append(category)
    if status == "low":
        sql += " AND p.stock_qty <= p.reorder_level"
    elif status == "out":
        sql += " AND p.stock_qty = 0"
    elif status == "expiring":
        sql += " AND p.expiry_date IS NOT NULL AND p.expiry_date <= date('now','+15 day')"
    return db.execute(sql + " ORDER BY p.name", args).fetchall()


def categories(db):
    return [r[0] for r in db.execute(
        "SELECT DISTINCT category FROM products ORDER BY category")]


def _integrity_msg(e):
    return "A product with that name already exists." if "UNIQUE" in str(e) else str(e)


def add_product(db, data):
    import sqlite3
    try:
        cur = db.execute(
            "INSERT INTO products(name,category,unit_price,stock_qty,reorder_level,"
            "expiry_date,supplier_id) VALUES (:name,:category,:unit_price,:stock_qty,"
            ":reorder_level,:expiry_date,:supplier_id)", data)
        db.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise ValidationError(_integrity_msg(e))


def update_product(db, product_id, data):
    import sqlite3
    try:
        db.execute(
            "UPDATE products SET name=:name,category=:category,unit_price=:unit_price,"
            "stock_qty=:stock_qty,reorder_level=:reorder_level,expiry_date=:expiry_date,"
            "supplier_id=:supplier_id WHERE product_id=:pid", {**data, "pid": product_id})
        db.commit()
    except sqlite3.IntegrityError as e:
        raise ValidationError(_integrity_msg(e))


def delete_product(db, product_id):
    """Delete a product. Products that appear on past bills cannot be deleted
    (to keep sales history intact); returns False in that case."""
    used = db.execute("SELECT 1 FROM sale_items WHERE product_id=? LIMIT 1",
                      (product_id,)).fetchone()
    if used:
        return False
    db.execute("DELETE FROM products WHERE product_id=?", (product_id,))
    db.commit()
    return True


CSV_COLUMNS = ["name", "category", "unit_price", "stock_qty", "reorder_level",
               "expiry_date", "supplier"]


def import_products_csv(db, text):
    """Import products from CSV text. Valid rows are inserted/updated (matched
    by name); bad rows are skipped and reported. Returns (added, updated, errors)."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationError("The CSV file is empty.")
    headers = {h.strip().lower() for h in reader.fieldnames if h}
    missing = {"name", "category", "unit_price", "stock_qty"} - headers
    if missing:
        raise ValidationError("CSV is missing required column(s): " + ", ".join(sorted(missing)))
    added = updated = 0
    errors = []
    for n, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            sup_name = row.get("supplier", "")
            if sup_name:
                s = db.execute("SELECT supplier_id FROM suppliers WHERE name=?",
                               (sup_name,)).fetchone()
                if not s:
                    cur = db.execute("INSERT INTO suppliers(name) VALUES (?)", (sup_name,))
                    row["supplier_id"] = str(cur.lastrowid)
                else:
                    row["supplier_id"] = str(s[0])
            data = validate_product(row)
            existing = db.execute("SELECT product_id FROM products WHERE name=?",
                                  (data["name"],)).fetchone()
            if existing:
                update_product(db, existing[0], data)
                updated += 1
            else:
                add_product(db, data)
                added += 1
        except ValidationError as e:
            errors.append(f"Row {n}: {e}")
    db.commit()
    return added, updated, errors


# ---- billing ------------------------------------------------------------
def create_bill(db, user_id, items, discount_pct=0, when=None):
    """Create a sale atomically.

    *items* is a list of (product_id, quantity). Duplicate products are merged.
    Validates quantities and stock, deducts stock and returns the new sale_id.
    Nothing is written if any line is invalid.
    """
    discount_pct = parse_discount(discount_pct)
    merged = {}
    for pid, qty in items:
        pid = parse_int(pid, "Product", 1)
        qty = parse_int(qty, "Quantity", 0)
        if qty == 0:
            continue
        merged[pid] = merged.get(pid, 0) + qty
    if not merged:
        raise ValidationError("Add at least one item with a quantity above zero.")

    when = when or datetime.now()
    try:
        db.execute("BEGIN IMMEDIATE")
        lines, subtotal = [], 0.0
        for pid, qty in merged.items():
            p = db.execute("SELECT name,unit_price,stock_qty FROM products WHERE product_id=?",
                           (pid,)).fetchone()
            if not p:
                raise ValidationError(f"Product #{pid} does not exist.")
            if qty > p["stock_qty"]:
                raise ValidationError(
                    f"Not enough stock for {p['name']}: requested {qty}, available {p['stock_qty']}.")
            lines.append((pid, qty, p["unit_price"]))
            subtotal += qty * p["unit_price"]
        subtotal = round(subtotal, 2)
        total = round(subtotal * (1 - discount_pct / 100), 2)
        cur = db.execute(
            "INSERT INTO sales(sale_date,sale_time,user_id,subtotal,discount_pct,total_amount)"
            " VALUES (?,?,?,?,?,?)",
            (when.strftime("%Y-%m-%d"), when.strftime("%H:%M:%S"), user_id,
             subtotal, discount_pct, total))
        sale_id = cur.lastrowid
        for pid, qty, price in lines:
            db.execute("INSERT INTO sale_items(sale_id,product_id,quantity,price) VALUES (?,?,?,?)",
                       (sale_id, pid, qty, price))
            db.execute("UPDATE products SET stock_qty = stock_qty - ? WHERE product_id=?",
                       (qty, pid))
        db.commit()
        return sale_id
    except Exception:
        db.rollback()
        raise


def get_sale(db, sale_id):
    sale = db.execute("SELECT s.*, u.username FROM sales s JOIN users u USING(user_id) "
                      "WHERE sale_id=?", (sale_id,)).fetchone()
    if not sale:
        return None, []
    items = db.execute("SELECT si.*, p.name, si.quantity*si.price AS line_total "
                       "FROM sale_items si JOIN products p USING(product_id) "
                       "WHERE sale_id=? ORDER BY sale_item_id", (sale_id,)).fetchall()
    return sale, items


def recent_sales(db, user_id=None, limit=10):
    sql = "SELECT s.*, u.username FROM sales s JOIN users u USING(user_id)"
    args = []
    if user_id:
        sql += " WHERE s.user_id=?"
        args.append(user_id)
    sql += " ORDER BY sale_date DESC, sale_time DESC, sale_id DESC LIMIT ?"
    return db.execute(sql, args + [limit]).fetchall()
