from datetime import date, timedelta

import pytest

from app import models, reports
from app.utils import ValidationError, parse_date, parse_int
from conftest import login


def stock(db, name):
    return db.execute("SELECT stock_qty FROM products WHERE name=?", (name,)).fetchone()[0]


def pid(db, name):
    return db.execute("SELECT product_id FROM products WHERE name=?", (name,)).fetchone()[0]


# ---- login ---------------------------------------------------------------
def test_login_success_and_wrong_password(client):
    assert b"Invalid username or password" in login(client, "admin", "nope").data
    assert b"Dashboard" in login(client, "admin", "adminpw").data


def test_password_is_hashed(db):
    h = db.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
    assert h != "adminpw" and h.startswith(("scrypt:", "pbkdf2:"))


def test_protected_pages_require_login(client):
    r = client.get("/products/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_cashier_cannot_open_admin_pages(client):
    login(client, "cash", "cashpw1")
    assert client.get("/products/").status_code == 403
    assert client.get("/reports/").status_code == 403
    assert client.get("/billing/").status_code == 200


# ---- billing & stock -----------------------------------------------------
def test_bill_total_discount_and_stock_deduction(db):
    sid = models.create_bill(db, 1, [(pid(db, "Milk"), 4), (pid(db, "Soap"), 2)], discount_pct=10)
    sale, items = models.get_sale(db, sid)
    assert sale["subtotal"] == 240.0 and sale["total_amount"] == 216.0
    assert len(items) == 2
    assert stock(db, "Milk") == 6 and stock(db, "Soap") == 98


def test_duplicate_lines_are_merged(db):
    sid = models.create_bill(db, 1, [(pid(db, "Milk"), 2), (pid(db, "Milk"), 3)])
    _, items = models.get_sale(db, sid)
    assert len(items) == 1 and items[0]["quantity"] == 5


def test_cannot_oversell_and_nothing_is_written(db):
    with pytest.raises(ValidationError, match="Not enough stock"):
        models.create_bill(db, 1, [(pid(db, "Soap"), 1), (pid(db, "Rice"), 4)])
    assert stock(db, "Rice") == 3 and stock(db, "Soap") == 100       # rolled back
    assert db.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0


@pytest.mark.parametrize("qty", ["-1", "abc", "1.5", ""])
def test_invalid_quantities_rejected(db, qty):
    with pytest.raises(ValidationError):
        models.create_bill(db, 1, [(pid(db, "Milk"), qty)])


@pytest.mark.parametrize("disc", ["-5", "101", "x"])
def test_invalid_discount_rejected(db, disc):
    with pytest.raises(ValidationError):
        models.create_bill(db, 1, [(pid(db, "Milk"), 1)], discount_pct=disc)


def test_empty_bill_rejected(db):
    with pytest.raises(ValidationError, match="at least one item"):
        models.create_bill(db, 1, [])


def test_bill_via_web_updates_stock(client, db):
    login(client, "cash", "cashpw1")
    r = client.post("/billing/", data={"product_id": [str(pid(db, "Milk"))], "quantity": ["2"],
                                       "discount": "0"}, follow_redirects=True)
    assert b"Bill created" in r.data and b"TOTAL" in r.data
    assert stock(db, "Milk") == 8


def test_web_bill_overselling_shows_friendly_error(client, db):
    login(client, "cash", "cashpw1")
    r = client.post("/billing/", data={"product_id": [str(pid(db, "Rice"))], "quantity": ["99"]})
    assert r.status_code == 200 and b"Not enough stock" in r.data


def test_receipt_pdf_and_csv(client, db):
    login(client, "cash", "cashpw1")
    sid = models.create_bill(db, 2, [(pid(db, "Milk"), 1)])
    assert client.get(f"/billing/receipt/{sid}.pdf").data.startswith(b"%PDF")
    assert b"TOTAL" in client.get(f"/billing/receipt/{sid}.csv").data


def test_cashier_cannot_view_other_cashiers_bill(client, db):
    sid = models.create_bill(db, 1, [(pid(db, "Milk"), 1)])      # user 1 = admin
    login(client, "cash", "cashpw1")
    assert client.get(f"/billing/receipt/{sid}").status_code == 403


# ---- product validation & CRUD ------------------------------------------
def test_product_validation():
    base = dict(name="X", category="C", unit_price="5", stock_qty="1", reorder_level="1")
    assert models.validate_product(base)["unit_price"] == 5.0
    for bad in ({"unit_price": "-1"}, {"stock_qty": "-3"}, {"expiry_date": "2025-13-45"},
                {"name": "  "}, {"unit_price": "abc"}):
        with pytest.raises(ValidationError):
            models.validate_product({**base, **bad})


def test_duplicate_product_name_rejected(db):
    with pytest.raises(ValidationError, match="already exists"):
        models.add_product(db, dict(name="milk", category="c", unit_price=1, stock_qty=1,
                                    reorder_level=1, expiry_date=None, supplier_id=None))


def test_search_and_delete_rules(db):
    assert [p["name"] for p in models.search_products(db, "ric")] == ["Rice"]
    assert {p["name"] for p in models.search_products(db, status="low")} == {"Rice"}
    models.create_bill(db, 1, [(pid(db, "Milk"), 1)])
    assert models.delete_product(db, pid(db, "Milk")) is False      # has sales history
    assert models.delete_product(db, pid(db, "Soap")) is True


def test_admin_product_crud_via_web(client, db):
    login(client, "admin", "adminpw")
    r = client.post("/products/new", data=dict(name="Tea", category="Bev", unit_price="99",
                    stock_qty="5", reorder_level="2", expiry_date="", supplier_id=""), follow_redirects=True)
    assert b"Product added" in r.data
    r = client.post("/products/new", data=dict(name="Bad", category="Bev", unit_price="-4",
                    stock_qty="5"), follow_redirects=True)
    assert b"cannot be negative" in r.data


# ---- CSV import ----------------------------------------------------------
def test_csv_import_adds_updates_and_reports_errors(db):
    csv_text = ("name,category,unit_price,stock_qty,reorder_level,expiry_date,supplier\n"
                "Butter,Dairy,60,20,5,2030-01-01,DairyCo\n"
                "Milk,Dairy,55,10,5,,\n"
                "Broken,Dairy,-1,5,5,,\n"
                "BadDate,Dairy,5,5,5,31/12/2030,\n")
    added, updated, errors = models.import_products_csv(db, csv_text)
    assert (added, updated, len(errors)) == (1, 1, 2)
    assert db.execute("SELECT unit_price FROM products WHERE name='Milk'").fetchone()[0] == 55
    assert "Row 4" in errors[0]


def test_csv_import_missing_columns(db):
    with pytest.raises(ValidationError, match="missing required"):
        models.import_products_csv(db, "name,category\nA,B\n")


# ---- helpers -------------------------------------------------------------
def test_parsers():
    assert parse_date("2024-02-29") == "2024-02-29"
    with pytest.raises(ValidationError):
        parse_date("2023-02-29")
    with pytest.raises(ValidationError):
        parse_int("-2", "Qty")


# ---- analytics -----------------------------------------------------------
def _sell(db, when, name, qty, disc=0):
    from datetime import datetime
    models.create_bill(db, 1, [(pid(db, name), qty)], disc, when=datetime.combine(when, datetime.min.time()))


def test_reports_and_kpis(db):
    today = date.today()
    _sell(db, today, "Soap", 5)                      # 100
    _sell(db, today - timedelta(days=1), "Milk", 4)  # 200
    _sell(db, today - timedelta(days=1), "Soap", 5, disc=50)  # 50
    s, e = (today - timedelta(days=5)).isoformat(), today.isoformat()
    d = reports.daily_sales(db, s, e)
    assert d["revenue"].tolist() == [250.0, 100.0] and d["bills"].tolist() == [2, 1]
    k = reports.kpis(db, s, e)
    assert k["total_revenue"] == 350.0 and k["bills"] == 3 and k["avg_bill"] == 116.67
    assert k["low_stock_count"] == 1                 # Rice
    top = reports.top_products(db, s, e)
    assert top.iloc[0]["name"] == "Milk"
    share = reports.category_share(db, s, e)
    assert round(share["share_pct"].sum(), 1) == 100.0
    assert reports.monthly_sales(db)["revenue"].sum() == 350.0


def test_slow_moving_low_stock_and_expiry(db):
    _sell(db, date.today(), "Milk", 8)               # fast mover
    slow = reports.slow_moving(db)
    assert "Milk" not in slow["name"].tolist() and "Soap" in slow["name"].tolist()
    assert reports.low_stock(db)["name"].tolist()[0] in ("Rice", "Milk")
    exp = reports.expiring(db).set_index("name")
    assert exp.loc["Soap", "status"] == "EXPIRED" and exp.loc["Milk", "days_left"] == 3


def test_reports_pages_charts_and_exports(client, db):
    _sell(db, date.today(), "Milk", 2)
    login(client, "admin", "adminpw")
    assert b"Total revenue" in client.get("/reports/").data
    for kind in ("daily", "monthly", "top", "category"):
        for metric in ("revenue", "quantity"):
            r = client.get(f"/reports/chart/{kind}.png?metric={metric}")
            assert r.status_code == 200 and r.data[:4] == b"\x89PNG"
    assert b"date,bills" in client.get("/reports/export/daily.csv").data
    assert b"End date" in client.get("/reports/?end=garbage").data      # friendly error, no crash
    assert b"Start date must not be after" in client.get("/reports/?start=2030-01-01&end=2020-01-01").data
