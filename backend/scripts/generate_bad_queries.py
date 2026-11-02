import os
import sys
import argparse
import json
import random
from pathlib import Path
from datetime import datetime

try:
    import psycopg
except ImportError:
    psycopg = None
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda: None

load_dotenv()
TARGET_DB_URL = os.getenv("TARGET_DATABASE_URL")

# ------------------------------------------------------------
# Query workload generation
# ------------------------------------------------------------
CATEGORIES = {
    "primary_key_lookup": {
        "template": "SELECT * FROM users WHERE user_id = %s;",
        "expected_issue": "healthy",
        "reason": "Direct lookup on PK is efficient",
        "requires_manual_review": false,
    },
    "unindexed_filter": {
        "template": "SELECT * FROM products WHERE price > %s;",
        "expected_issue": "needs_index",
        "reason": "Filtering on price column without an index may cause full scan",
        "requires_manual_review": false,
    },
    "large_result": {
        "template": "SELECT * FROM order_items;",
        "expected_issue": "full_table_scan",
        "reason": "Selecting all rows without filter triggers full scan",
        "requires_manual_review": false,
    },
    "join_query": {
        "template": "SELECT o.order_id, u.full_name, p.product_name FROM orders o "
                    "JOIN users u ON o.user_id = u.user_id "
                    "JOIN order_items oi ON o.order_id = oi.order_id "
                    "JOIN products p ON oi.product_id = p.product_id "
                    "WHERE o.status = %s LIMIT 10;",
        "expected_issue": "healthy",
        "reason": "Join with filters on indexed FK columns",
        "requires_manual_review": false,
    },
    "aggregation": {
        "template": "SELECT u.city, COUNT(*) as orders_cnt FROM orders o "
                    "JOIN users u ON o.user_id = u.user_id "
                    "GROUP BY u.city;",
        "expected_issue": "healthy",
        "reason": "Aggregation with GROUP BY on indexed column",
        "requires_manual_review": false,
    },
    "select_star": {
        "template": "SELECT * FROM products;",
        "expected_issue": "healthy",
        "reason": "SELECT * is not inherently bad; may be acceptable for small tables",
        "requires_manual_review": false,
    },
    "query_rewrite": {
        "template": "SELECT * FROM orders WHERE status = %s AND order_date > %s;",
        "expected_issue": "query_rewrite",
        "reason": "Could be rewritten to use index on (status, order_date) if created",
        "requires_manual_review": true,
    },
}

ISSUE_LABELS = {"needs_index", "query_rewrite", "full_table_scan", "healthy"}

def generate_query_instances(seed: int, instances_per_category: int = 5):
    random.seed(seed)
    queries = []
    query_id = 1
    for cat, meta in CATEGORIES.items():
        for _ in range(instances_per_category):
            # Generate simple parameters based on category
            if cat == "primary_key_lookup":
                param = random.randint(1, 10000)
            elif cat == "unindexed_filter":
                param = round(random.uniform(10, 100), 2)
            elif cat == "join_query":
                param = random.choice(["pending", "shipped", "delivered"])
            elif cat == "query_rewrite":
                param_status = random.choice(["processed", "cancelled"])
                param_date = datetime.now().strftime("%Y-%m-%d")
                param = [param_status, param_date]
            else:
                param = None

            queries.append({
                "query_id": query_id,
                "query_template": meta["template"],
                "query_category": cat,
                "expected_issue": meta["expected_issue"],
                "expected_reason": meta["reason"],
                "parameters": param,
                "requires_manual_review": meta["requires_manual_review"],
            })
            query_id += 1
    return queries

def write_queries_to_file(queries, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps(q) + "\n")
    print(f"✅ Wrote {len(queries)} query templates to {output_path}")

def execute_queries(conn, queries):
    # Use a read‑only transaction
    with conn.cursor() as cur:
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cur.execute("SET statement_timeout = '30s'")
        for q in queries:
            try:
                cur.execute(q["query_template"], q["parameters"] if isinstance(q["parameters"], (list, tuple)) else (q["parameters"],) if q["parameters"] is not None else ())
                cur.fetchall()
                print(f"Executed query_id={q['query_id']} successfully")
            except Exception as e:
                print(f"Error executing query_id={q['query_id']}: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Generate synthetic query workload for the e‑commerce target schema.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Generate query templates without connecting to the database (default).")
    parser.add_argument("--execute", action="store_true", help="Execute the generated queries against the target DB (requires confirmation).")
    parser.add_argument("--confirm-target-db", action="store_true", help="Acknowledge that TARGET_DATABASE_URL points to a dedicated dev DB for execution.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility (default 42).")
    parser.add_argument("--instances-per-category", type=int, default=5, help="Number of query examples per category.")
    parser.add_argument("--output-dir", type=Path, default=Path("backend/data/workload"), help="Directory to write query_templates.jsonl.")
    args = parser.parse_args()

    queries = generate_query_instances(args.seed, args.instances_per_category)
    output_file = args.output_dir / "query_templates.jsonl"
    write_queries_to_file(queries, output_file)

    if args.execute:
        if not args.confirm_target_db:
            print("⚠️  You must pass --confirm-target-db to execute queries.", file=sys.stderr)
            sys.exit(1)
        # Ensure the target DB is not the same as the project DB
        project_db_url = os.getenv("PROJECT_DATABASE_URL")
        if project_db_url and TARGET_DB_URL == project_db_url:
            print("⚠️  TARGET_DATABASE_URL matches PROJECT_DATABASE_URL. Refusing to operate on the project database.", file=sys.stderr)
            sys.exit(1)
        if not TARGET_DB_URL:
            print("Error: TARGET_DATABASE_URL environment variable is not set.", file=sys.stderr)
            sys.exit(1)
        try:
            conn = psycopg.connect(TARGET_DB_URL)
        except Exception as exc:
            print(f"❌ Could not connect to TARGET_DATABASE_URL: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            execute_queries(conn, queries)
        finally:
            conn.close()


if __name__ == "__main__":
    main()
