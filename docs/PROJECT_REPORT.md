# Project Report – GreenLeaf Grocers Inventory & Sales System

## 1. Problem
GreenLeaf Grocers tracked stock and sales on paper/spreadsheets, causing stock-outs, expiry losses, billing errors and no visibility of top sellers. The goal: one application for products, stock, billing and reporting.

## 2. Design
- **Stack:** Python, Flask, SQLite (`sqlite3`), pandas, matplotlib, reportlab (PDF bills).
- **Database:** five tables (`users`, `suppliers`, `products`, `sales`, `sale_items`) in third normal form – see `er_diagram.png`. Constraints: PKs, FKs, UNIQUE names/usernames, CHECKs for prices, stock, quantity, discount and role. Indexes on sale date and foreign keys.
- **Code organisation:** `database` (connections/schema), `models` (data access & business rules), `routes` (Flask blueprints), `reports` (pandas analytics), `utils` (validation/auth).
- **Security:** hashed passwords, session login, role checks (403 for cashiers on admin pages; cashiers see only their own bills), CSRF tokens, parameterised SQL, Jinja auto-escaping, 2 MB upload cap.

## 3. Key logic
- **Billing** (`models.create_bill`): validates input, merges duplicate lines, runs in `BEGIN IMMEDIATE` transaction, checks stock for every line, inserts sale + items, deducts stock; any failure rolls back everything.
- **Analytics:** SQL joins load sale lines into pandas DataFrames; groupby produces daily/monthly revenue, top-10, category share, slow movers, expiry and low-stock lists and the five KPIs.
- **Forecast (bonus):** weekday-average revenue over the last 8 weeks projected 7 days ahead.

## 4. Testing
29 pytest tests with a temporary database per test: login/roles, password hashing, billing totals & discount, stock deduction, rollback on oversell, invalid quantity/discount/date, duplicate products, delete rules, CSV import, KPI/report maths with hand-computed values, chart endpoints, CSV/PDF export. All pass (`docs/test_report.txt`).

## 5. Challenges & how they were handled
| Challenge | Solution |
|---|---|
| Overselling when two bills race | Single write transaction (`BEGIN IMMEDIATE`) with stock check inside it |
| Deleting a product with sales history | Blocked with a clear message to keep history consistent |
| Price changes altering old bills | Unit price copied into `sale_items.price` |
| Discounts distorting category/product revenue | Bill discount apportioned to lines for product-level analytics |
| Messy CSV uploads | Per-row validation; good rows imported, bad rows listed with row numbers |

## 6. Learnings
Putting business rules in one tested function (not in routes) made the web layer thin; DB-level constraints are a useful second line of defence; pandas makes report logic short and testable; realistic seed data (with dead stock, expired items, weekday patterns) is essential to see reports work.

## 7. Limitations & future work
SQLite suits a single store; use PostgreSQL for multi-store. Possible additions: purchase orders/receiving stock, e-mail low-stock alerts, barcode scanning, user management UI, better forecasting (e.g. Prophet).
