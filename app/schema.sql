PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','cashier'))
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    phone       TEXT,
    email       TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category      TEXT NOT NULL,
    unit_price    REAL NOT NULL CHECK (unit_price >= 0),
    stock_qty     INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 10 CHECK (reorder_level >= 0),
    expiry_date   TEXT,                       -- ISO date YYYY-MM-DD, NULL = non-perishable
    supplier_id   INTEGER REFERENCES suppliers(supplier_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS sales (
    sale_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_date    TEXT NOT NULL,               -- YYYY-MM-DD
    sale_time    TEXT NOT NULL,               -- HH:MM:SS
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    subtotal     REAL NOT NULL CHECK (subtotal >= 0),
    discount_pct REAL NOT NULL DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 100),
    total_amount REAL NOT NULL CHECK (total_amount >= 0)
);

CREATE TABLE IF NOT EXISTS sale_items (
    sale_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id      INTEGER NOT NULL REFERENCES sales(sale_id) ON DELETE CASCADE,
    product_id   INTEGER NOT NULL REFERENCES products(product_id),
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    price        REAL NOT NULL CHECK (price >= 0)   -- unit price at time of sale
);

CREATE INDEX IF NOT EXISTS idx_sales_date  ON sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_items_sale  ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_items_prod  ON sale_items(product_id);
CREATE INDEX IF NOT EXISTS idx_prod_cat    ON products(category);
