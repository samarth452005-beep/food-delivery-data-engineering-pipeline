"""Reusable data-quality checks for the DuckDB fact_orders table."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def validate_orders(db_path, start_date, end_date):
    con = duckdb.connect(str(db_path))
    try:
        latest = con.execute("""
            SELECT run_id
            FROM pipeline_runs
            WHERE status = 'SUCCESS'
              AND batch_start_date = CAST(? AS DATE)
              AND batch_end_date = CAST(? AS DATE)
            ORDER BY started_at DESC
            LIMIT 1
        """, [start_date, end_date]).fetchone()

        if latest is None:
            raise ValueError("No successful matching pipeline run found.")

        run_id = latest[0]

        checks = [
            (
                "No null order IDs",
                "SELECT COUNT(*) FROM fact_orders WHERE order_id IS NULL",
                0
            ),
            (
                "Unique order IDs",
                """
                SELECT COUNT(*) - COUNT(DISTINCT order_id)
                FROM fact_orders
                """,
                0
            ),
            (
                "No null dates or statuses",
                """
                SELECT COUNT(*) FROM fact_orders
                WHERE order_date IS NULL OR order_status IS NULL
                """,
                0
            ),
            (
                "No negative sales amounts",
                """
                SELECT COUNT(*) FROM fact_orders
                WHERE sales_amount < 0
                """,
                0
            ),
            (
                "Expected batch row count",
                """
                SELECT COUNT(*) FROM fact_orders
                WHERE order_date BETWEEN CAST(? AS DATE)
                                     AND CAST(? AS DATE)
                """,
                None
            ),
        ]

        expected_count = con.execute("""
            SELECT COUNT(*) FROM read_parquet(?)
            WHERE order_date BETWEEN CAST(? AS DATE)
                                 AND CAST(? AS DATE)
        """, [
            str(Path(db_path).parent / "parquet" / "orders.parquet"),
            start_date, end_date
        ]).fetchone()[0]

        results = []
        checked_at = datetime.now(timezone.utc)

        for name, sql, expected in checks:
            params = []
            if name == "Expected batch row count":
                expected = expected_count
                params = [start_date, end_date]

            actual = con.execute(sql, params).fetchone()[0]
            results.append({
                "run_id": run_id,
                "check_name": name,
                "expected_value": int(expected),
                "actual_value": int(actual),
                "status": "PASS" if actual == expected else "FAIL",
                "checked_at": checked_at.isoformat(),
            })

        con.execute("""
            CREATE TABLE IF NOT EXISTS data_quality_results (
                run_id VARCHAR,
                check_name VARCHAR,
                expected_value BIGINT,
                actual_value BIGINT,
                status VARCHAR,
                checked_at TIMESTAMPTZ
            )
        """)

        con.execute(
            "DELETE FROM data_quality_results WHERE run_id = ?",
            [run_id]
        )

        con.executemany("""
            INSERT INTO data_quality_results
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            (
                r["run_id"], r["check_name"], r["expected_value"],
                r["actual_value"], r["status"], checked_at
            )
            for r in results
        ])

        print(json.dumps(results, indent=2))
        return results
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()

    results = validate_orders(
        args.db, args.start_date, args.end_date
    )

    if any(r["status"] != "PASS" for r in results):
        raise SystemExit("One or more data-quality checks failed.")
