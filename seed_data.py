"""Generate sample data: users, suppliers, 60+ products, 600+ sales over ~6 months.

Usage:  python seed_data.py            (recreates data/greenleaf.db)
        python seed_data.py --db path  (custom path)
"""
import argparse
import os
import random
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

from app import database

CATALOG = {  # category: [(name, price)]
    "Fruits & Vegetables": [("Bananas 1kg", 48), ("Apples 1kg", 180), ("Tomatoes 1kg", 40), ("Potatoes 1kg", 35),
        ("Onions 1kg", 38), ("Spinach Bunch", 20), ("Carrots 500g", 30), ("Mangoes 1kg", 120)],
    "Dairy & Eggs": [("Full Cream Milk 1L", 68), ("Curd 500g", 40), ("Paneer 200g", 90), ("Butter 100g", 58),
        ("Cheese Slices 200g", 140), ("Eggs (12)", 84), ("Greek Yogurt 400g", 110)],
    "Bakery": [("Whole Wheat Bread", 45), ("White Bread", 40), ("Multigrain Bun (4)", 55), ("Chocolate Muffin", 35), ("Croissant", 50)],
    "Grains & Staples": [("Basmati Rice 5kg", 540), ("Wheat Flour 5kg", 230), ("Toor Dal 1kg", 160), ("Sugar 1kg", 46),
        ("Iodised Salt 1kg", 22), ("Sunflower Oil 1L", 150), ("Moong Dal 1kg", 125), ("Poha 500g", 48)],
    "Beverages": [("Green Tea (25 bags)", 175), ("Instant Coffee 100g", 290), ("Orange Juice 1L", 110), ("Cola 750ml", 40),
        ("Mineral Water 1L", 20), ("Tea Powder 500g", 240), ("Coconut Water 200ml", 45)],
    "Snacks": [("Potato Chips 100g", 30), ("Salted Peanuts 200g", 55), ("Digestive Biscuits", 60), ("Dark Chocolate 80g", 150),
        ("Namkeen Mix 200g", 65), ("Cookies 150g", 45), ("Instant Noodles (4)", 56)],
    "Household": [("Dish Wash Liquid 500ml", 110), ("Laundry Detergent 1kg", 220), ("Toilet Cleaner 500ml", 95),
        ("Paper Towels (2)", 90), ("Garbage Bags (30)", 80), ("Floor Cleaner 1L", 170)],
    "Personal Care": [("Bath Soap (4)", 140), ("Shampoo 340ml", 260), ("Toothpaste 150g", 95), ("Hand Wash 250ml", 85),
        ("Body Lotion 400ml", 280)],
}
PERISHABLE = {"Fruits & Vegetables": 5, "Dairy & Eggs": 14, "Bakery": 4, "Beverages": 120, "Snacks": 150,
              "Grains & Staples": 300}
SUPPLIERS = [("Fresh Farms Pvt Ltd", "9876500011", "orders@freshfarms.example"),
             ("DairyBest Co-op", "9876500022", "sales@dairybest.example"),
             ("Metro Wholesale Traders", "9876500033", "info@metro.example"),
             ("CleanHome Distributors", "9876500044", "hello@cleanhome.example"),
             ("Sunrise Foods", "9876500055", "supply@sunrise.example")]
SUP_FOR = {"Fruits & Vegetables": 1, "Dairy & Eggs": 2, "Bakery": 5, "Grains & Staples": 3, "Beverages": 3,
           "Snacks": 5, "Household": 4, "Personal Care": 4}


def seed(db_path, seed_value=42, days=180, n_sales=650):
    rnd = random.Random(seed_value)
    if os.path.exists(db_path):
        os.remove(db_path)
    database.init_db(db_path)
    db = database.connect(db_path)
    db.executemany("INSERT INTO users(username,password_hash,role) VALUES (?,?,?)", [
        ("admin", generate_password_hash("admin123"), "admin"),
        ("cashier", generate_password_hash("cashier123"), "cashier"),
        ("priya", generate_password_hash("priya123"), "cashier")])
    db.executemany("INSERT INTO suppliers(name,phone,email) VALUES (?,?,?)", SUPPLIERS)

    today = date.today()
    products = []   # (id, price, popularity)
    for cat, items in CATALOG.items():
        for name, price in items:
            shelf = PERISHABLE.get(cat)
            expiry = (today + timedelta(days=rnd.randint(-2, shelf * 2))).isoformat() if shelf else None
            reorder = rnd.choice([10, 15, 20, 25])
            stock = rnd.choice([0, 3, 8, 12, 25, 40, 60, 90, 120, 150])
            cur = db.execute(
                "INSERT INTO products(name,category,unit_price,stock_qty,reorder_level,expiry_date,supplier_id)"
                " VALUES (?,?,?,?,?,?,?)", (name, cat, price, stock, reorder, expiry, SUP_FOR[cat]))
            # a few "dead" products so the slow-moving report has content
            pop = 0.0 if rnd.random() < 0.08 else rnd.choice([1, 1, 2, 3, 5, 8])
            products.append((cur.lastrowid, price, pop))
    live = [p for p in products if p[2] > 0]
    weights = [p[2] for p in live]
    users = [1, 2, 3]
    for _ in range(n_sales):
        d = today - timedelta(days=rnd.randint(0, days - 1))
        t = datetime(d.year, d.month, d.day, rnd.randint(8, 21), rnd.randint(0, 59), rnd.randint(0, 59))
        picks = {}
        for pid, price, _ in rnd.choices(live, weights=weights, k=rnd.randint(1, 7)):
            picks[pid] = (price, picks.get(pid, (price, 0))[1] + rnd.randint(1, 4))
        subtotal = round(sum(p * q for p, q in picks.values()), 2)
        disc = rnd.choice([0, 0, 0, 0, 5, 5, 10])
        total = round(subtotal * (1 - disc / 100), 2)
        sid = db.execute("INSERT INTO sales(sale_date,sale_time,user_id,subtotal,discount_pct,total_amount)"
                         " VALUES (?,?,?,?,?,?)",
                         (t.strftime("%Y-%m-%d"), t.strftime("%H:%M:%S"), rnd.choice(users), subtotal, disc, total)).lastrowid
        db.executemany("INSERT INTO sale_items(sale_id,product_id,quantity,price) VALUES (?,?,?,?)",
                       [(sid, pid, q, p) for pid, (p, q) in picks.items()])
    db.commit()
    counts = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("users", "suppliers", "products", "sales", "sale_items")}
    db.close()
    return counts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "data", "greenleaf.db"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.db), exist_ok=True)
    print("Seeded:", seed(a.db))
    print("Logins -> admin/admin123 , cashier/cashier123")
