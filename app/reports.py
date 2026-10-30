"""pandas-based analytics: reports, KPIs and matplotlib charts."""
import io
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

GREEN, GREY = "#2f7d4f", "#6b7280"


def _sales_df(db, start=None, end=None):
    """One row per sale line, with line_total and sale-level discount."""
    q = ("SELECT s.sale_id, s.sale_date, s.discount_pct, s.total_amount, "
         "si.product_id, p.name, p.category, si.quantity, si.price, "
         "si.quantity*si.price AS line_total "
         "FROM sales s JOIN sale_items si USING(sale_id) "
         "JOIN products p USING(product_id) WHERE 1=1")
    args = []
    if start:
        q += " AND s.sale_date >= ?"; args.append(start)
    if end:
        q += " AND s.sale_date <= ?"; args.append(end)
    df = pd.read_sql_query(q, db, params=args)
    if not df.empty:
        # net line value after the bill-level discount
        df["net_total"] = df["line_total"] * (1 - df["discount_pct"] / 100)
    else:
        df["net_total"] = pd.Series(dtype=float)
    return df


def _bills_df(db, start=None, end=None):
    q = "SELECT sale_id, sale_date, total_amount FROM sales WHERE 1=1"
    args = []
    if start:
        q += " AND sale_date >= ?"; args.append(start)
    if end:
        q += " AND sale_date <= ?"; args.append(end)
    return pd.read_sql_query(q, db, params=args)


def daily_sales(db, start, end):
    b = _bills_df(db, start, end)
    if b.empty:
        return pd.DataFrame(columns=["date", "bills", "revenue", "quantity"])
    items = _sales_df(db, start, end).groupby("sale_date")["quantity"].sum()
    g = b.groupby("sale_date").agg(bills=("sale_id", "count"), revenue=("total_amount", "sum"))
    g["quantity"] = items
    g = g.reset_index().rename(columns={"sale_date": "date"})
    g["revenue"] = g["revenue"].round(2)
    g["quantity"] = g["quantity"].fillna(0).astype(int)
    return g


def monthly_sales(db, start=None, end=None):
    d = daily_sales(db, start, end)
    if d.empty:
        return pd.DataFrame(columns=["month", "bills", "revenue", "quantity"])
    d["month"] = d["date"].str[:7]
    m = d.groupby("month")[["bills", "revenue", "quantity"]].sum().reset_index()
    m["revenue"] = m["revenue"].round(2)
    return m


def top_products(db, start, end, n=10, metric="revenue"):
    df = _sales_df(db, start, end)
    if df.empty:
        return pd.DataFrame(columns=["name", "category", "quantity", "revenue"])
    g = df.groupby(["name", "category"]).agg(quantity=("quantity", "sum"),
                                              revenue=("net_total", "sum")).reset_index()
    g["revenue"] = g["revenue"].round(2)
    key = "quantity" if metric == "quantity" else "revenue"
    return g.sort_values(key, ascending=False).head(n).reset_index(drop=True)


def category_share(db, start, end):
    df = _sales_df(db, start, end)
    if df.empty:
        return pd.DataFrame(columns=["category", "quantity", "revenue", "share_pct"])
    g = df.groupby("category").agg(quantity=("quantity", "sum"),
                                   revenue=("net_total", "sum")).reset_index()
    g["share_pct"] = (g["revenue"] / g["revenue"].sum() * 100).round(1)
    g["revenue"] = g["revenue"].round(2)
    return g.sort_values("revenue", ascending=False).reset_index(drop=True)


def slow_moving(db, days=30, max_units=2, today=None):
    """Products in stock that sold <= max_units in the last *days* days."""
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    prods = pd.read_sql_query(
        "SELECT product_id,name,category,stock_qty,unit_price FROM products WHERE stock_qty>0", db)
    sold = _sales_df(db, since, today.isoformat())
    units = sold.groupby("product_id")["quantity"].sum() if not sold.empty else pd.Series(dtype=int)
    prods["units_sold"] = prods["product_id"].map(units).fillna(0).astype(int)
    out = prods[prods["units_sold"] <= max_units].copy()
    out["stock_value"] = (out["stock_qty"] * out["unit_price"]).round(2)
    return out.sort_values(["units_sold", "stock_value"], ascending=[True, False]) \
              .drop(columns="product_id").reset_index(drop=True)


def low_stock(db):
    return pd.read_sql_query(
        "SELECT p.name,p.category,p.stock_qty,p.reorder_level,"
        "(p.reorder_level*2 - p.stock_qty) AS suggested_order, s.name AS supplier, s.phone "
        "FROM products p LEFT JOIN suppliers s USING(supplier_id) "
        "WHERE p.stock_qty <= p.reorder_level ORDER BY p.stock_qty - p.reorder_level", db)


def expiring(db, days=15, today=None):
    today = today or date.today()
    limit = (today + timedelta(days=days)).isoformat()
    df = pd.read_sql_query(
        "SELECT name,category,stock_qty,expiry_date FROM products "
        "WHERE expiry_date IS NOT NULL AND expiry_date <= ? ORDER BY expiry_date",
        db, params=[limit])
    df["days_left"] = (pd.to_datetime(df["expiry_date"]) - pd.Timestamp(today)).dt.days
    df["status"] = df["days_left"].apply(lambda d: "EXPIRED" if d < 0 else "Expiring soon")
    return df


def kpis(db, start, end):
    bills = _bills_df(db, start, end)
    revenue = float(bills["total_amount"].sum()) if not bills.empty else 0.0
    n = len(bills)
    items = _sales_df(db, start, end)
    sold_units = int(items["quantity"].sum()) if not items.empty else 0
    cur_stock = int(db.execute("SELECT COALESCE(SUM(stock_qty),0) FROM products").fetchone()[0])
    opening = cur_stock + sold_units                  # stock at start of period
    avg_inv = (opening + cur_stock) / 2
    turnover = round(sold_units / avg_inv, 2) if avg_inv else 0.0
    cats = category_share(db, start, end)
    return {
        "total_revenue": round(revenue, 2),
        "bills": n,
        "avg_bill": round(revenue / n, 2) if n else 0.0,
        "stock_turnover": turnover,
        "low_stock_count": int(db.execute(
            "SELECT COUNT(*) FROM products WHERE stock_qty <= reorder_level").fetchone()[0]),
        "top_category": cats.iloc[0]["category"] if not cats.empty else "—",
        "top_category_share": float(cats.iloc[0]["share_pct"]) if not cats.empty else 0.0,
    }


def forecast_next_7_days(db, today=None):
    """Bonus: naive forecast = mean revenue for each weekday over the last 8 weeks."""
    today = today or date.today()
    d = daily_sales(db, (today - timedelta(days=56)).isoformat(), today.isoformat())
    out = []
    if d.empty:
        return pd.DataFrame(columns=["date", "weekday", "forecast_revenue"])
    d["wd"] = pd.to_datetime(d["date"]).dt.weekday
    by_wd, overall = d.groupby("wd")["revenue"].mean(), d["revenue"].mean()
    for i in range(1, 8):
        day = today + timedelta(days=i)
        out.append({"date": day.isoformat(), "weekday": day.strftime("%a"),
                    "forecast_revenue": round(float(by_wd.get(day.weekday(), overall)), 2)})
    return pd.DataFrame(out)


# ---- charts -------------------------------------------------------------
def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _empty(msg="No sales in this period"):
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.text(.5, .5, msg, ha="center", va="center", color=GREY); ax.axis("off")
    return _png(fig)


def chart(db, kind, start, end, metric="revenue"):
    """Return PNG bytes for kind in daily|monthly|top|category."""
    col = "quantity" if metric == "quantity" else "revenue"
    label = "Units sold" if col == "quantity" else "Revenue (₹)"
    if kind == "daily":
        d = daily_sales(db, start, end)
        if d.empty: return _empty()
        fig, ax = plt.subplots(figsize=(8, 3.6))
        ax.plot(pd.to_datetime(d["date"]), d[col], color=GREEN, lw=2)
        ax.fill_between(pd.to_datetime(d["date"]), d[col], color=GREEN, alpha=.12)
        ax.set_title(f"Daily {label.lower()}")
        fig.autofmt_xdate()
    elif kind == "monthly":
        m = monthly_sales(db)
        if m.empty: return _empty()
        fig, ax = plt.subplots(figsize=(8, 3.6))
        ax.bar(m["month"], m[col], color=GREEN)
        ax.set_title(f"Monthly {label.lower()}")
    elif kind == "top":
        t = top_products(db, start, end, 10, col)
        if t.empty: return _empty()
        t = t.iloc[::-1]
        fig, ax = plt.subplots(figsize=(8, 4.2))
        ax.barh(t["name"], t[col], color=GREEN)
        ax.set_title(f"Top 10 products by {label.lower()}")
    elif kind == "category":
        c = category_share(db, start, end)
        if c.empty: return _empty()
        fig, ax = plt.subplots(figsize=(6, 4.2))
        ax.pie(c[col], labels=c["category"], autopct="%1.0f%%", startangle=90,
               colors=plt.cm.Greens([0.35 + 0.6 * i / max(len(c), 1) for i in range(len(c))][::-1]),
               wedgeprops={"edgecolor": "white"})
        ax.set_title(f"Category share ({label.lower()})")
    else:
        return _empty("Unknown chart")
    if kind != "category":
        ax.set_ylabel(label) if kind != "top" else ax.set_xlabel(label)
        for s in ("top", "right"): ax.spines[s].set_visible(False)
        ax.grid(alpha=.25)
    return _png(fig)
