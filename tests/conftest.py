import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app, database, models  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    """App bound to a throw-away test database (never touches data/greenleaf.db)."""
    app = create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True,
                      "CSRF_ENABLED": False, "SECRET_KEY": "test"})
    with app.app_context():
        db = database.get_db()
        models.create_user(db, "admin", "adminpw", "admin")
        models.create_user(db, "cash", "cashpw1", "cashier")
        today = date.today()
        for name, cat, price, stock, rl, exp in [
            ("Milk", "Dairy", 50.0, 10, 5, (today + timedelta(days=3)).isoformat()),
            ("Rice", "Grains", 100.0, 3, 5, None),
            ("Soap", "Care", 20.0, 100, 10, (today - timedelta(days=1)).isoformat())]:
            models.add_product(db, dict(name=name, category=cat, unit_price=price, stock_qty=stock,
                                        reorder_level=rl, expiry_date=exp, supplier_id=None))
    return app


@pytest.fixture()
def db(app):
    with app.app_context():
        yield database.get_db()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, user, pw):
    return client.post("/login", data={"username": user, "password": pw}, follow_redirects=True)
