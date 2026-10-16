"""Incremental order ingestion prototype using DuckDB and Parquet."""

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def utc_now():
    return datetime.now(timezone.utc)


def run_pipeline(db_path, parquet_path, start_date, end_date):
    db_path = Path(db_path)
    parquet_path = Path(parquet_path)

    if not parquet_path.exists():
        raise FileNotFoundError(f"Source file not found: {parquet_path}")

    run_id = str(uuid.uuid4())
    started = utc_now()
    clock = time.perf_counter()
    status = "SUCCESS"
    error_message = None
    rows_processed = 0
    rows_before = 0
    rows_after = 0
    rows_inserted_net = 0

    con = duckdb.connect(str(db_path))

    try:
        con.execute("SET threads = 2")

        con.execute("""
            CREATE TABLE IF NOT EXISTS fact_orders (
                order_id BIGINT PRIMARY KEY,
                order_timestamp TIMESTAMP,
                order_date DATE,
                user_id BIGINT,
                r_id BIGINT,
                restaurant_city VARCHAR,
                cuisine VARCHAR,
                items_count BIGINT,
                sales_qty BIGINT,
                subtotal BIGINT,
                discount BIGINT,
                delivery_fee BIGINT,
                gst BIGINT,
                sales_amount BIGINT,
                currency VARCHAR,
                payment_method VARCHAR,
                order_status VARCHAR,
                customer_rating DOUBLE,
                delivery_time_min DOUBLE
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id VARCHAR PRIMARY KEY,
                status VARCHAR,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                duration_seconds DOUBLE,
                source_file VARCHAR,
                batch_start_date DATE,
                batch_end_date DATE,
                rows_processed BIGINT,
                rows_before BIGINT,
                rows_after BIGINT,
                rows_inserted_net BIGINT,
                error_message VARCHAR
            )
        """)

        rows_before = con.execute(
            "SELECT COUNT(*) FROM fact_orders"
        ).fetchone()[0]

        rows_processed = con.execute("""
            SELECT COUNT(*)
            FROM read_parquet(?)
            WHERE order_date BETWEEN CAST(? AS DATE)
                                 AND CAST(? AS DATE)
        """, [str(parquet_path), start_date, end_date]).fetchone()[0]

        columns = [
            "order_id", "order_timestamp", "order_date", "user_id",
            "r_id", "restaurant_city", "cuisine", "items_count",
            "sales_qty", "subtotal", "discount", "delivery_fee", "gst",
            "sales_amount", "currency", "payment_method", "order_status",
            "customer_rating", "delivery_time_min"
        ]

        column_sql = ", ".join(columns)
        update_sql = ", ".join(
            f"{col} = EXCLUDED.{col}"
            for col in columns if col != "order_id"
        )

        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(f"""
                INSERT INTO fact_orders ({column_sql})
                SELECT {column_sql}
                FROM read_parquet(?)
                WHERE order_date BETWEEN CAST(? AS DATE)
                                     AND CAST(? AS DATE)
                ON CONFLICT (order_id) DO UPDATE SET {update_sql}
            """, [str(parquet_path), start_date, end_date])

            rows_after = con.execute(
                "SELECT COUNT(*) FROM fact_orders"
            ).fetchone()[0]

            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        rows_inserted_net = rows_after - rows_before

    except Exception as exc:
        status = "FAILED"
        error_message = str(exc)

    finally:
        finished = utc_now()
        duration = round(time.perf_counter() - clock, 3)

        record = {
            "run_id": run_id,
            "status": status,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_seconds": duration,
            "source_file": parquet_path.name,
            "batch_start_date": start_date,
            "batch_end_date": end_date,
            "rows_processed": rows_processed,
            "rows_before": rows_before,
            "rows_after": rows_after,
            "rows_inserted_net": rows_inserted_net,
            "error_message": error_message,
        }

        try:
            con.execute("""
                INSERT INTO pipeline_runs VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT (run_id) DO NOTHING
            """, [
                record["run_id"], record["status"], started, finished,
                duration, record["source_file"], start_date, end_date,
                rows_processed, rows_before, rows_after,
                rows_inserted_net, error_message
            ])
        finally:
            con.close()

        log_dir = db_path.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "pipeline_runs.jsonl").open("a") as log:
            log.write(json.dumps(record) + "\n")

    print(json.dumps(record, indent=2))

    if status != "SUCCESS":
        raise RuntimeError(f"Pipeline failed: {error_message}")

    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()

    run_pipeline(
        args.db,
        args.source,
        args.start_date,
        args.end_date
    )
