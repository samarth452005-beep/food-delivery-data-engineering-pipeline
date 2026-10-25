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

def discover_parquet_files(incoming_dir):
    """Return sorted Parquet files waiting in the incoming directory."""
    incoming_dir = Path(incoming_dir)

    if not incoming_dir.exists():
        return []

    return sorted(
        path
        for path in incoming_dir.glob("*.parquet")
        if path.is_file()
    )

def ensure_file_registry(con):
    """Create a registry for tracking incoming Parquet files."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS processed_files (
            file_path VARCHAR PRIMARY KEY,
            file_name VARCHAR NOT NULL,
            file_size_bytes BIGINT NOT NULL,
            file_modified_at TIMESTAMP,
            status VARCHAR NOT NULL,
            discovered_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMPTZ,
            error_message VARCHAR
        )
    """)

def register_incoming_file(con, file_path):
    """Register a file and return whether it needs processing."""
    file_path = Path(file_path).resolve()

    if not file_path.is_file():
        raise FileNotFoundError(f"Source file not found: {file_path}")

    if file_path.suffix.lower() != ".parquet":
        raise ValueError("Only Parquet files can be registered.")

    stat = file_path.stat()
    file_name = file_path.name
    file_size = stat.st_size
    modified_at = datetime.fromtimestamp(
        stat.st_mtime, timezone.utc
    ).replace(tzinfo=None)

    existing = con.execute("""
        SELECT file_size_bytes, file_modified_at, status
        FROM processed_files
        WHERE file_path = ?
    """, [str(file_path)]).fetchone()

    if existing is None:
        con.execute("""
            INSERT INTO processed_files (
                file_path, file_name, file_size_bytes,
                file_modified_at, status
            )
            VALUES (?, ?, ?, ?, 'DISCOVERED')
        """, [str(file_path), file_name, file_size, modified_at])
        return True

    old_size, old_modified, old_status = existing

    if old_size != file_size or old_modified != modified_at:
        con.execute("""
            UPDATE processed_files
            SET file_name = ?,
                file_size_bytes = ?,
                file_modified_at = ?,
                status = 'DISCOVERED',
                processed_at = NULL,
                error_message = NULL
            WHERE file_path = ?
        """, [file_name, file_size, modified_at, str(file_path)])
        return True

    return old_status != "SUCCESS"


def update_file_status(con, file_path, status, error_message=None):
    """Record the processing outcome for a registered file."""
    if status not in {"SUCCESS", "FAILED"}:
        raise ValueError("Status must be SUCCESS or FAILED.")

    file_path = str(Path(file_path).resolve())

    # Check registration before attempting the update.
    exists = con.execute("""
        SELECT COUNT(*)
        FROM processed_files
        WHERE file_path = ?
    """, [file_path]).fetchone()[0]

    if exists == 0:
        raise ValueError(f"File is not registered: {file_path}")

    if status == "SUCCESS":
        con.execute("""
            UPDATE processed_files
            SET status = 'SUCCESS',
                processed_at = CURRENT_TIMESTAMP,
                error_message = NULL
            WHERE file_path = ?
        """, [file_path])
    else:
        con.execute("""
            UPDATE processed_files
            SET status = 'FAILED',
                error_message = ?
            WHERE file_path = ?
        """, [error_message, file_path])


def run_pipeline(db_path, parquet_path, start_date, end_date):

    # Validate dates before opening the database.
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Dates must use YYYY-MM-DD format, for example 2026-01-31."
        ) from exc

    if start > end:
        raise ValueError(
            "start_date must be earlier than or equal to end_date."
        )

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
    rows_inserted = 0
    rows_updated = 0

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
                rows_inserted BIGINT DEFAULT 0,
                rows_updated BIGINT DEFAULT 0,
                error_message VARCHAR
            )
        """)


        rows_before = con.execute(
            "SELECT COUNT(*) FROM fact_orders"
        ).fetchone()[0]

        # Data quality check: order IDs must not be NULL.
        null_order_ids = con.execute("""
            SELECT COUNT(*)
            FROM read_parquet(?)
            WHERE order_date BETWEEN CAST(? AS DATE)
                                 AND CAST(? AS DATE)
              AND order_id IS NULL
        """, [str(parquet_path), start_date, end_date]).fetchone()[0]

        if null_order_ids > 0:
            raise ValueError(
                f"Data quality check failed: found {null_order_ids} "
                "rows with NULL order_id values."
            )

        # Data quality check: reject duplicate order IDs in the batch.
        duplicate_order_ids = con.execute("""
            SELECT COUNT(*)
            FROM (
                SELECT order_id
                FROM read_parquet(?)
                WHERE order_date BETWEEN CAST(? AS DATE)
                                     AND CAST(? AS DATE)
                GROUP BY order_id
                HAVING COUNT(*) > 1
            ) AS duplicates
        """, [
            str(parquet_path), start_date, end_date
        ]).fetchone()[0]

        if duplicate_order_ids > 0:
            raise ValueError(
                "Data quality check failed: found "
                f"{duplicate_order_ids} duplicate order_id values."
            )

        # Data quality check: reject negative sales amounts.
        negative_sales = con.execute("""
            SELECT COUNT(*)
            FROM read_parquet(?)
            WHERE order_date BETWEEN CAST(? AS DATE)
                                 AND CAST(? AS DATE)
              AND sales_amount < 0
        """, [
            str(parquet_path), start_date, end_date
        ]).fetchone()[0]

        if negative_sales > 0:
            raise ValueError(
                "Data quality check failed: found "
                f"{negative_sales} rows with negative sales_amount."
            )

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
            # Count orders that do not exist in the target table yet.
            rows_inserted = con.execute("""
                SELECT COUNT(*)
                FROM read_parquet(?) AS src
                LEFT JOIN fact_orders AS target
                    ON src.order_id = target.order_id
                WHERE src.order_date BETWEEN CAST(? AS DATE)
                                         AND CAST(? AS DATE)
                  AND target.order_id IS NULL
            """, [
                str(parquet_path), start_date, end_date
            ]).fetchone()[0]

            # Count existing orders whose values have changed.
            comparison_columns = [
                col for col in columns if col != "order_id"
            ]
            differences = " OR ".join(
                f"src.{col} IS DISTINCT FROM target.{col}"
                for col in comparison_columns
            )

            rows_updated = con.execute(f"""
                SELECT COUNT(*)
                FROM read_parquet(?) AS src
                INNER JOIN fact_orders AS target
                    ON src.order_id = target.order_id
                WHERE src.order_date BETWEEN CAST(? AS DATE)
                                         AND CAST(? AS DATE)
                  AND ({differences})
            """, [
                str(parquet_path), start_date, end_date
            ]).fetchone()[0]

            # Insert new orders and update existing orders.
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
            "rows_inserted": rows_inserted,
            "rows_updated": rows_updated,
        }

        try:

            con.execute("""
                INSERT INTO pipeline_runs (
                    run_id, status, started_at, finished_at,
                    duration_seconds, source_file,
                    batch_start_date, batch_end_date,
                    rows_processed, rows_before, rows_after,
                    rows_inserted_net, rows_inserted, rows_updated,
                    error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO NOTHING
            """, [
                record["run_id"],
                record["status"],
                started,
                finished,
                duration,
                record["source_file"],
                start_date,
                end_date,
                rows_processed,
                rows_before,
                rows_after,
                rows_inserted_net,
                rows_inserted,
                rows_updated,
                error_message,
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


def process_incoming_files(
    db_path,
    incoming_dir,
    start_date,
    end_date,
):
    """Discover incoming files and process eligible Parquet files."""
    db_path = Path(db_path)
    incoming_dir = Path(incoming_dir)

    results = []

    # Discover files without modifying them.
    files = discover_parquet_files(incoming_dir)

    # Create and use the registry.
    with duckdb.connect(str(db_path)) as con:
        ensure_file_registry(con)

        for file_path in files:
            try:
                should_process = register_incoming_file(
                    con, file_path
                )

                if not should_process:
                    results.append({
                        "file": file_path.name,
                        "status": "SKIPPED",
                        "reason": "Already processed successfully",
                    })
                    continue

            except Exception as exc:
                results.append({
                    "file": file_path.name,
                    "status": "FAILED",
                    "error": str(exc),
                })
                continue

            # Release the registry connection before ingestion.
            # run_pipeline opens its own DuckDB connection.
            con.execute("CHECKPOINT")

            try:
                run_pipeline(
                    db_path,
                    file_path,
                    start_date,
                    end_date,
                )

                with duckdb.connect(str(db_path)) as status_con:
                    update_file_status(
                        status_con, file_path, "SUCCESS"
                    )

                results.append({
                    "file": file_path.name,
                    "status": "SUCCESS",
                })

            except Exception as exc:
                with duckdb.connect(str(db_path)) as status_con:
                    update_file_status(
                        status_con,
                        file_path,
                        "FAILED",
                        error_message=str(exc),
                    )

                results.append({
                    "file": file_path.name,
                    "status": "FAILED",
                    "error": str(exc),
                })

    return results



if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Food delivery incremental ingestion pipeline"
    )

    parser.add_argument("--db", required=True, help="DuckDB database path")
    parser.add_argument(
        "--start-date", required=True, help="Batch start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date", required=True, help="Batch end date (YYYY-MM-DD)"
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--incoming-dir",
        help="Directory containing incoming Parquet files",
    )
    mode.add_argument(
        "--source",
        help="Process one specific Parquet file",
    )

    args = parser.parse_args()

    try:
        if args.incoming_dir:
            results = process_incoming_files(
                args.db,
                args.incoming_dir,
                args.start_date,
                args.end_date,
            )
            print(json.dumps(results, indent=2))
        else:
            result = run_pipeline(
                args.db,
                args.source,
                args.start_date,
                args.end_date,
            )
            print(json.dumps(result, indent=2))

    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        parser.exit(1, f"Pipeline error: {exc}\n")
