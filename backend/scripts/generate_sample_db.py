import os
import sys
import argparse
import random
import string
from datetime import datetime, timezone
from pathlib import Path
import psycopg

# Load environment variables (TARGET_DATABASE_URL)
from dotenv import load_dotenv
load_dotenv()

if not TARGET_DB_URL:
    print("Error: TARGET_DATABASE_URL environment variable is not set.", file=sys.stderr)
    sys.exit(1)
# Ensure the target DB is not the same as the QueryDoctor project DB
PROJECT_DB_URL = os.getenv("PROJECT_DATABASE_URL")
if PROJECT_DB_URL and TARGET_DB_URL == PROJECT_DB_URL:
    print("⚠️  TARGET_DATABASE_URL matches PROJECT_DATABASE_URL. Refusing to operate on the project database.", file=sys.stderr)
    sys.exit(1)

# ------------------------------------------------------------
# Schema definitions (target e‑commerce DB)
# ------------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGSERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
    product_id BIGSERIAL PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    price NUMERIC CHECK (price > 0) NOT NULL,
    stock_quantity INTEGER CHECK (stock_quantity >= 0) NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    order_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    status VARCHAR(20) NOT NULL,
    total_amount NUMERIC CHECK (total_amount >= 0) NOT NULL,
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INTEGER CHECK (quantity > 0) NOT NULL,
    unit_price NUMERIC CHECK (unit_price > 0) NOT NULL,
    CONSTRAINT fk_oi_order FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE RESTRICT,
    CONSTRAINT fk_oi_product FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT
);

-- Indexes for foreign‑key look‑ups (primary keys already have indexes)
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON order_items(product_id);
"""

# ------------------------------------------------------------
# Synthetic data generation helpers
# ------------------------------------------------------------
CITIES = ["New York", "London", "Paris", "Berlin", "Tokyo", "Sydney", "Toronto", "San Francisco", "Mumbai", "São Paulo"]
PRODUCT_CATEGORIES = ["Electronics", "Books", "Clothing", "Home", "Sports", "Toys", "Food", "Beauty", "Automotive", "Garden"]
ORDER_STATUSES = ["pending", "processed", "shipped", "delivered", "cancelled"]

def generate_users(count):
    """Return a list of tuples (full_name, email, city)."""
    return [(f"User {i}", f"user{i}@example.com", random.choice(CITIES)) for i in range(1, count + 1)]

def generate_products(count):
    return [(f"Product {i}", random.choice(PRODUCT_CATEGORIES), round(random.uniform(5.0, 500.0), 2), random.randint(0, 1000))
            for i in range(1, count + 1)]

def generate_orders(count, user_ids):
    orders = []
    for _ in range(count):
        user_id = random.choice(user_ids)
        order_date = datetime.now(timezone.utc).isoformat()
        status = random.choice(ORDER_STATUSES)
        orders.append((user_id, order_date, status, 0.0))  # total_amount placeholder
    return orders

def generate_order_items(order_ids, product_ids, avg_items_per_order=3):
    items = []
    order_totals = {oid: 0.0 for oid in order_ids}
    for oid in order_ids:
        # each order gets 1‑(2*avg) items to add variance
        num_items = random.randint(1, max(1, int(avg_items_per_order * 2)))
        for _ in range(num_items):
            pid = random.choice(product_ids)
            qty = random.randint(1, 5)
            unit_price = round(random.uniform(5.0, 500.0), 2)
            line_total = qty * unit_price
            order_totals[oid] += line_total
            items.append((oid, pid, qty, unit_price))
    return items, order_totals

def batch_execute(cur, sql, data, batch_size=1000):
    """Insert rows in batches using executemany."""
    for i in range(0, len(data), batch_size):
        cur.executemany(sql, data[i:i + batch_size])

def create_schema(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()
    print("✅ Target e‑commerce schema ensured.")

def seed_data(conn, users_cnt, products_cnt, orders_cnt, seed):
    random.seed(seed)
    print(f"🔧 Seeding synthetic data (seed={seed}) …")

    # Users
    users = generate_users(users_cnt)
    with conn.cursor() as cur:
        batch_execute(cur, "INSERT INTO users (full_name, email, city) VALUES (%s, %s, %s)", users)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM users ORDER BY user_id")
        user_ids = [row[0] for row in cur.fetchall()]

    # Products
    products = generate_products(products_cnt)
    with conn.cursor() as cur:
        batch_execute(cur, "INSERT INTO products (product_name, category, price, stock_quantity) VALUES (%s, %s, %s, %s)", products)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT product_id FROM products ORDER BY product_id")
        product_ids = [row[0] for row in cur.fetchall()]

    # Orders (total_amount placeholder 0)
    orders = generate_orders(orders_cnt, user_ids)
    with conn.cursor() as cur:
        batch_execute(cur, "INSERT INTO orders (user_id, order_date, status, total_amount) VALUES (%s, %s, %s, %s)", orders)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT order_id FROM orders ORDER BY order_id")
        order_ids = [row[0] for row in cur.fetchall()]

    # Order items + compute totals
    items, totals = generate_order_items(order_ids, product_ids)
    with conn.cursor() as cur:
        batch_execute(cur, "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)", items)
    conn.commit()

    # Update order totals
    with conn.cursor() as cur:
        for oid, total in totals.items():
            cur.execute("UPDATE orders SET total_amount = %s WHERE order_id = %s", (round(total, 2), oid))
    conn.commit()

    print("✅ Synthetic data seeded.")
    print(f"   Users: {users_cnt}, Products: {products_cnt}, Orders: {orders_cnt}, Order items: {len(items)}")

def main():
    parser = argparse.ArgumentParser(
        description="Generate the e‑commerce target database schema and optional synthetic data.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--create-schema", action="store_true", help="Create the tables (no data).")
    parser.add_argument("--seed-data", action="store_true", help="Insert synthetic data after schema exists.")
    parser.add_argument("--confirm-target-db", action="store_true", help="Acknowledge that TARGET_DATABASE_URL points to a dedicated dev DB.")
    parser.add_argument("--users", type=int, default=10_000, help="Number of users (default 10,000).")
    parser.add_argument("--products", type=int, default=1_000, help="Number of products (default 1,000).")
    parser.add_argument("--orders", type=int, default=50_000, help="Number of orders (default 50,000).")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility (default 42).")
    args = parser.parse_args()

    if not args.confirm_target_db:
        print("⚠️  You must pass --confirm-target-db to allow any write operation.", file=sys.stderr)
        sys.exit(1)

    try:
        conn = psycopg.connect(TARGET_DB_URL)
    except Exception as exc:
        print(f"❌ Failed to connect to TARGET_DATABASE_URL: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.create_schema:
            create_schema(conn)
        if args.seed_data:
            seed_data(conn, args.users, args.products, args.orders, args.seed)
        if not args.create_schema and not args.seed_data:
            parser.print_help()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
