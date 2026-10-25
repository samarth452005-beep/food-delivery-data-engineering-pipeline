
import pandas as pd 
import pytest

from src.incremental_pipeline import run_pipeline


def test_reprocessing_same_parquet_does_not_duplicate_orders(tmp_path):
    source = tmp_path / "orders.parquet"
    database = tmp_path / "pipeline.duckdb"

    df = pd.DataFrame({
        "order_id": [101, 102],
        "order_timestamp": pd.to_datetime([
            "2026-01-01 10:00:00",
            "2026-01-02 11:00:00",
        ]),
        "order_date": pd.to_datetime([
            "2026-01-01",
            "2026-01-02",
        ]).date,
        "user_id": [1, 2],
        "r_id": [10, 20],
        "restaurant_city": ["Bhopal", "Indore"],
        "cuisine": ["Indian", "Italian"],
        "items_count": [2, 1],
        "sales_qty": [2, 1],
        "subtotal": [400, 250],
        "discount": [0, 10],
        "delivery_fee": [30, 25],
        "gst": [20, 15],
        "sales_amount": [450, 280],
        "currency": ["INR", "INR"],
        "payment_method": ["UPI", "Card"],
        "order_status": ["Delivered", "Cancelled"],
        "customer_rating": [4.5, 3.5],
        "delivery_time_min": [25.0, 35.0],
    })

    df.to_parquet(source, index=False)

    first_run = run_pipeline(
        database,
        source,
        "2026-01-01",
        "2026-01-31",
    )

    second_run = run_pipeline(
        database,
        source,
        "2026-01-01",
        "2026-01-31",
    )

    assert first_run["status"] == "SUCCESS"
    assert first_run["rows_processed"] == 2
    assert first_run["rows_after"] == 2

    assert second_run["status"] == "SUCCESS"
    assert second_run["rows_processed"] == 2
    assert second_run["rows_after"] == 2
    assert second_run["rows_inserted_net"] == 0


def test_reprocessing_updates_existing_order(tmp_path):
    source = tmp_path / "orders.parquet"
    database = tmp_path / "pipeline.duckdb"

    df = pd.DataFrame({
        "order_id": [101],
        "order_timestamp": pd.to_datetime(["2026-01-01 10:00:00"]),
        "order_date": pd.to_datetime(["2026-01-01"]).date,
        "user_id": [1],
        "r_id": [10],
        "restaurant_city": ["Bhopal"],
        "cuisine": ["Indian"],
        "items_count": [2],
        "sales_qty": [2],
        "subtotal": [400],
        "discount": [0],
        "delivery_fee": [30],
        "gst": [20],
        "sales_amount": [450],
        "currency": ["INR"],
        "payment_method": ["UPI"],
        "order_status": ["Delivered"],
        "customer_rating": [4.5],
        "delivery_time_min": [25.0],
    })

    df.to_parquet(source, index=False)

    run_pipeline(database, source, "2026-01-01", "2026-01-31")

    # Simulate a correction to an existing order.
    df.loc[0, "sales_amount"] = 500
    df.to_parquet(source, index=False)

    result = run_pipeline(
        database, source, "2026-01-01", "2026-01-31"
    )

    import duckdb

    with duckdb.connect(str(database)) as conn:
        order_count = conn.execute(
            "SELECT COUNT(*) FROM fact_orders"
        ).fetchone()[0]

        sales_amount = conn.execute(
            "SELECT sales_amount FROM fact_orders WHERE order_id = 101"
        ).fetchone()[0]

    assert result["status"] == "SUCCESS"
    assert order_count == 1
    assert sales_amount == 500


def test_pipeline_run_metrics_are_saved(tmp_path):
    import duckdb

    source = tmp_path / "orders.parquet"
    database = tmp_path / "pipeline.duckdb"

    df = pd.DataFrame({
        "order_id": [101, 102],
        "order_timestamp": pd.to_datetime([
            "2026-01-01 10:00:00",
            "2026-01-02 11:00:00",
        ]),
        "order_date": pd.to_datetime([
            "2026-01-01", "2026-01-02"
        ]).date,
        "user_id": [1, 2],
        "r_id": [10, 20],
        "restaurant_city": ["Bhopal", "Indore"],
        "cuisine": ["Indian", "Italian"],
        "items_count": [2, 1],
        "sales_qty": [2, 1],
        "subtotal": [400, 250],
        "discount": [0, 10],
        "delivery_fee": [30, 25],
        "gst": [20, 15],
        "sales_amount": [450, 280],
        "currency": ["INR", "INR"],
        "payment_method": ["UPI", "Card"],
        "order_status": ["Delivered", "Cancelled"],
        "customer_rating": [4.5, 3.5],
        "delivery_time_min": [25.0, 35.0],
    })

    df.to_parquet(source, index=False)

    first = run_pipeline(
        database, source, "2026-01-01", "2026-01-31"
    )

    with duckdb.connect(str(database), read_only=True) as con:
        saved = con.execute("""
            SELECT rows_inserted, rows_updated
            FROM pipeline_runs
            WHERE run_id = ?
        """, [first["run_id"]]).fetchone()

    assert saved == (2, 0)

from src.incremental_pipeline import discover_parquet_files


def test_discover_parquet_files_finds_only_parquet_files(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    (incoming / "orders_b.parquet").touch()
    (incoming / "orders_a.parquet").touch()
    (incoming / "notes.txt").touch()

    discovered = discover_parquet_files(incoming)

    assert [path.name for path in discovered] == [
        "orders_a.parquet",
        "orders_b.parquet",
    ]


def test_discover_parquet_files_returns_empty_for_missing_folder(tmp_path):
    missing = tmp_path / "does_not_exist"

    assert discover_parquet_files(missing) == []

def test_file_registry_is_created(tmp_path):
    import duckdb
    from src.incremental_pipeline import ensure_file_registry

    database = tmp_path / "registry.duckdb"

    with duckdb.connect(str(database)) as con:
        ensure_file_registry(con)

        columns = con.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'processed_files'
            ORDER BY ordinal_position
        """).fetchall()

    column_names = [column[0] for column in columns]

    assert "file_path" in column_names
    assert "file_name" in column_names
    assert "status" in column_names
    assert "processed_at" in column_names
    assert "error_message" in column_names

def test_register_incoming_file_skips_unchanged_successful_file(tmp_path):
    import duckdb
    from src.incremental_pipeline import (
        ensure_file_registry,
        register_incoming_file,
    )

    database = tmp_path / "registry.duckdb"
    source = tmp_path / "orders.parquet"
    source.write_bytes(b"test parquet placeholder")

    with duckdb.connect(str(database)) as con:
        ensure_file_registry(con)

        assert register_incoming_file(con, source) is True

        con.execute("""
            UPDATE processed_files
            SET status = 'SUCCESS',
                processed_at = CURRENT_TIMESTAMP
            WHERE file_path = ?
        """, [str(source.resolve())])

        assert register_incoming_file(con, source) is False

def test_register_incoming_file_detects_changed_file(tmp_path):
    import duckdb
    from src.incremental_pipeline import (
        ensure_file_registry,
        register_incoming_file,
    )

    database = tmp_path / "registry.duckdb"
    source = tmp_path / "orders.parquet"
    source.write_bytes(b"first version")

    with duckdb.connect(str(database)) as con:
        ensure_file_registry(con)

        assert register_incoming_file(con, source) is True

        con.execute("""
            UPDATE processed_files
            SET status = 'SUCCESS',
                processed_at = CURRENT_TIMESTAMP
            WHERE file_path = ?
        """, [str(source.resolve())])

        # Replace the file with different content and a different size.
        source.write_bytes(b"updated version with more data")

        assert register_incoming_file(con, source) is True

def test_update_file_status_marks_file_successful(tmp_path):
    import duckdb
    from src.incremental_pipeline import (
        ensure_file_registry,
        register_incoming_file,
        update_file_status,
    )

    database = tmp_path / "registry.duckdb"
    source = tmp_path / "orders.parquet"
    source.write_bytes(b"placeholder")

    with duckdb.connect(str(database)) as con:
        ensure_file_registry(con)
        register_incoming_file(con, source)

        update_file_status(con, source, "SUCCESS")

        result = con.execute("""
            SELECT status, processed_at, error_message
            FROM processed_files
            WHERE file_path = ?
        """, [str(source.resolve())]).fetchone()

        assert result[0] == "SUCCESS"
        assert result[1] is not None
        assert result[2] is None

def test_update_file_status_records_failure(tmp_path):
    import duckdb
    from src.incremental_pipeline import (
        ensure_file_registry,
        register_incoming_file,
        update_file_status,
    )

    database = tmp_path / "registry.duckdb"
    source = tmp_path / "orders.parquet"
    source.write_bytes(b"placeholder")

    with duckdb.connect(str(database)) as con:
        ensure_file_registry(con)
        register_incoming_file(con, source)

        update_file_status(
            con,
            source,
            "FAILED",
            error_message="Invalid Parquet file",
        )

        result = con.execute("""
            SELECT status, error_message, processed_at
            FROM processed_files
            WHERE file_path = ?
        """, [str(source.resolve())]).fetchone()

        assert result[0] == "FAILED"
        assert result[1] == "Invalid Parquet file"
        assert result[2] is None

def test_process_incoming_files_processes_new_file(tmp_path):
    import duckdb
    from src.incremental_pipeline import process_incoming_files

    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "orders.parquet"
    database = tmp_path / "pipeline.duckdb"

    df = pd.DataFrame({
        "order_id": [101],
        "order_timestamp": pd.to_datetime(["2026-01-01 10:00:00"]),
        "order_date": pd.to_datetime(["2026-01-01"]).date,
        "user_id": [1],
        "r_id": [10],
        "restaurant_city": ["Bhopal"],
        "cuisine": ["Indian"],
        "items_count": [2],
        "sales_qty": [2],
        "subtotal": [400],
        "discount": [0],
        "delivery_fee": [30],
        "gst": [20],
        "sales_amount": [450],
        "currency": ["INR"],
        "payment_method": ["UPI"],
        "order_status": ["Delivered"],
        "customer_rating": [4.5],
        "delivery_time_min": [25.0],
    })
    df.to_parquet(source, index=False)

    results = process_incoming_files(
        database,
        incoming,
        "2026-01-01",
        "2026-01-31",
    )

    assert len(results) == 1
    assert results[0]["status"] == "SUCCESS"

    with duckdb.connect(str(database), read_only=True) as con:
        order_count = con.execute(
            "SELECT COUNT(*) FROM fact_orders"
        ).fetchone()[0]

        file_status = con.execute("""
            SELECT status
            FROM processed_files
            WHERE file_name = 'orders.parquet'
        """).fetchone()[0]

    assert order_count == 1
    assert file_status == "SUCCESS"

def test_process_incoming_files_skips_successful_file(tmp_path):
    import duckdb
    from src.incremental_pipeline import process_incoming_files

    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "orders.parquet"
    database = tmp_path / "pipeline.duckdb"

    df = pd.DataFrame({
        "order_id": [101],
        "order_timestamp": pd.to_datetime(["2026-01-01 10:00:00"]),
        "order_date": pd.to_datetime(["2026-01-01"]).date,
        "user_id": [1],
        "r_id": [10],
        "restaurant_city": ["Bhopal"],
        "cuisine": ["Indian"],
        "items_count": [2],
        "sales_qty": [2],
        "subtotal": [400],
        "discount": [0],
        "delivery_fee": [30],
        "gst": [20],
        "sales_amount": [450],
        "currency": ["INR"],
        "payment_method": ["UPI"],
        "order_status": ["Delivered"],
        "customer_rating": [4.5],
        "delivery_time_min": [25.0],
    })
    df.to_parquet(source, index=False)

    first = process_incoming_files(
        database, incoming, "2026-01-01", "2026-01-31"
    )
    second = process_incoming_files(
        database, incoming, "2026-01-01", "2026-01-31"
    )

    assert first[0]["status"] == "SUCCESS"
    assert second[0]["status"] == "SKIPPED"

    with duckdb.connect(str(database), read_only=True) as con:
        order_count = con.execute(
            "SELECT COUNT(*) FROM fact_orders"
        ).fetchone()[0]

        run_count = con.execute(
            "SELECT COUNT(*) FROM pipeline_runs"
        ).fetchone()[0]

    assert order_count == 1
    assert run_count == 1

def test_failed_file_can_be_retried(tmp_path):
    import duckdb
    from src.incremental_pipeline import (
        ensure_file_registry,
        register_incoming_file,
        update_file_status,
    )

    database = tmp_path / "registry.duckdb"
    source = tmp_path / "orders.parquet"
    source.write_bytes(b"placeholder")

    with duckdb.connect(str(database)) as con:
        ensure_file_registry(con)

        assert register_incoming_file(con, source) is True

        update_file_status(
            con,
            source,
            "FAILED",
            error_message="Temporary processing error",
        )

        assert register_incoming_file(con, source) is True

        update_file_status(con, source, "SUCCESS")

        assert register_incoming_file(con, source) is False

def test_pipeline_rejects_invalid_date_format(tmp_path):
    from src.incremental_pipeline import run_pipeline

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run_pipeline(
            tmp_path / "pipeline.duckdb",
            tmp_path / "missing.parquet",
            "01-01-2026",
            "2026-01-31",
        )


def test_pipeline_rejects_reversed_date_range(tmp_path):
    from src.incremental_pipeline import run_pipeline

    with pytest.raises(ValueError, match="start_date"):
        run_pipeline(
            tmp_path / "pipeline.duckdb",
            tmp_path / "missing.parquet",
            "2026-02-01",
            "2026-01-01",
        )

def test_process_incoming_files_records_invalid_parquet_failure(tmp_path):
    import duckdb
    from src.incremental_pipeline import process_incoming_files

    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "broken.parquet"
    source.write_bytes(b"this is not a valid parquet file")

    database = tmp_path / "pipeline.duckdb"

    results = process_incoming_files(
        database,
        incoming,
        "2026-01-01",
        "2026-01-31",
    )

    assert len(results) == 1
    assert results[0]["status"] == "FAILED"

    with duckdb.connect(str(database), read_only=True) as con:
        status, error_message = con.execute("""
            SELECT status, error_message
            FROM processed_files
            WHERE file_name = 'broken.parquet'
        """).fetchone()

    assert status == "FAILED"
    assert error_message is not None
    assert error_message != ""


def test_registration_detects_content_change_with_same_size_and_mtime(tmp_path):
    import os

    import duckdb
    from src.incremental_pipeline import (
        ensure_file_registry,
        register_incoming_file,
    )

    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "orders.parquet"
    source.write_bytes(b"first-content")
    original_stat = source.stat()

    database = tmp_path / "registry.duckdb"

    with duckdb.connect(str(database)) as con:
        ensure_file_registry(con)

        # Register the initial version.
        assert register_incoming_file(con, source) is True

        # Change contents but preserve size and modification time.
        source.write_bytes(b"other-content")
        os.utime(
            source,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )

        # The changed contents should still be detected.
        assert register_incoming_file(con, source) is True

def test_pipeline_rejects_null_order_id(tmp_path):
    import duckdb
    import pytest

    from src.incremental_pipeline import run_pipeline

    source = tmp_path / "null_order_id.parquet"
    database = tmp_path / "pipeline.duckdb"

    with duckdb.connect() as con:
        con.execute("""
            COPY (
                SELECT
                    NULL::BIGINT AS order_id,
                    TIMESTAMP '2026-01-10 12:00:00' AS order_timestamp,
                    DATE '2026-01-10' AS order_date,
                    501::BIGINT AS user_id,
                    101::BIGINT AS r_id,
                    'Bhopal'::VARCHAR AS restaurant_city,
                    'Indian'::VARCHAR AS cuisine,
                    2::BIGINT AS items_count,
                    2::BIGINT AS sales_qty,
                    450::BIGINT AS subtotal,
                    0::BIGINT AS discount,
                    30::BIGINT AS delivery_fee,
                    20::BIGINT AS gst,
                    500::BIGINT AS sales_amount,
                    'INR'::VARCHAR AS currency,
                    'UPI'::VARCHAR AS payment_method,
                    'Delivered'::VARCHAR AS order_status,
                    4.5::DOUBLE AS customer_rating,
                    25.0::DOUBLE AS delivery_time_min
            ) TO '""" + str(source).replace("\\", "/") + """'
            (FORMAT PARQUET)
        """)

    with pytest.raises(RuntimeError, match="order_id"):
        run_pipeline(
            database,
            source,
            "2026-01-01",
            "2026-01-31",
        )

    with duckdb.connect(str(database), read_only=True) as con:
        row_count = con.execute(
            "SELECT COUNT(*) FROM fact_orders"
        ).fetchone()[0]

    assert row_count == 0

def test_pipeline_rejects_duplicate_order_ids(tmp_path):
    import duckdb
    import pytest

    from src.incremental_pipeline import run_pipeline

    source = tmp_path / "duplicate_orders.parquet"
    database = tmp_path / "pipeline.duckdb"

    with duckdb.connect() as con:
        con.execute("""
            COPY (
                SELECT *
                FROM (
                    VALUES
                    (1001::BIGINT, TIMESTAMP '2026-01-10 12:00:00',
                     DATE '2026-01-10', 501::BIGINT, 101::BIGINT,
                     'Bhopal', 'Indian', 2::BIGINT, 2::BIGINT,
                     450::BIGINT, 0::BIGINT, 30::BIGINT, 20::BIGINT,
                     500::BIGINT, 'INR', 'UPI', 'Delivered',
                     4.5::DOUBLE, 25.0::DOUBLE),
                    (1001::BIGINT, TIMESTAMP '2026-01-10 13:00:00',
                     DATE '2026-01-10', 501::BIGINT, 101::BIGINT,
                     'Bhopal', 'Indian', 2::BIGINT, 2::BIGINT,
                     600::BIGINT, 0::BIGINT, 30::BIGINT, 20::BIGINT,
                     650::BIGINT, 'INR', 'UPI', 'Delivered',
                     4.0::DOUBLE, 30.0::DOUBLE)
                ) AS orders(
                    order_id, order_timestamp, order_date, user_id,
                    r_id, restaurant_city, cuisine, items_count,
                    sales_qty, subtotal, discount, delivery_fee, gst,
                    sales_amount, currency, payment_method, order_status,
                    customer_rating, delivery_time_min
                )
            ) TO '""" + str(source).replace("\\", "/") + """'
            (FORMAT PARQUET)
        """)

    with pytest.raises(RuntimeError, match="duplicate order_id"):
        run_pipeline(
            database,
            source,
            "2026-01-01",
            "2026-01-31",
        )

    with duckdb.connect(str(database), read_only=True) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM fact_orders"
        ).fetchone()[0]

    assert count == 0

def test_pipeline_rejects_negative_sales_amount(tmp_path):
    import duckdb
    import pytest

    from src.incremental_pipeline import run_pipeline

    source = tmp_path / "negative_sales.parquet"
    database = tmp_path / "pipeline.duckdb"

    with duckdb.connect() as con:
        con.execute("""
            COPY (
                SELECT
                    1001::BIGINT AS order_id,
                    TIMESTAMP '2026-01-10 12:00:00' AS order_timestamp,
                    DATE '2026-01-10' AS order_date,
                    501::BIGINT AS user_id,
                    101::BIGINT AS r_id,
                    'Bhopal'::VARCHAR AS restaurant_city,
                    'Indian'::VARCHAR AS cuisine,
                    2::BIGINT AS items_count,
                    2::BIGINT AS sales_qty,
                    450::BIGINT AS subtotal,
                    0::BIGINT AS discount,
                    30::BIGINT AS delivery_fee,
                    20::BIGINT AS gst,
                    -500::BIGINT AS sales_amount,
                    'INR'::VARCHAR AS currency,
                    'UPI'::VARCHAR AS payment_method,
                    'Delivered'::VARCHAR AS order_status,
                    4.5::DOUBLE AS customer_rating,
                    25.0::DOUBLE AS delivery_time_min
            ) TO '""" + str(source).replace("\\", "/") + """'
            (FORMAT PARQUET)
        """)

    with pytest.raises(RuntimeError, match="negative sales_amount"):
        run_pipeline(
            database,
            source,
            "2026-01-01",
            "2026-01-31",
        )

    with duckdb.connect(str(database), read_only=True) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM fact_orders"
        ).fetchone()[0]

    assert count == 0

def test_pipeline_rolls_back_batch_when_one_row_is_invalid(tmp_path):
    import duckdb
    import pytest

    from src.incremental_pipeline import run_pipeline

    source = tmp_path / "mixed_orders.parquet"
    database = tmp_path / "pipeline.duckdb"

    with duckdb.connect() as con:
        con.execute("""
            COPY (
                SELECT *
                FROM (
                    VALUES
                    (1001::BIGINT, TIMESTAMP '2026-01-10 12:00:00',
                     DATE '2026-01-10', 501::BIGINT, 101::BIGINT,
                     'Bhopal', 'Indian', 2::BIGINT, 2::BIGINT,
                     450::BIGINT, 0::BIGINT, 30::BIGINT, 20::BIGINT,
                     500::BIGINT, 'INR', 'UPI', 'Delivered',
                     4.5::DOUBLE, 25.0::DOUBLE),
                    (1002::BIGINT, TIMESTAMP '2026-01-10 13:00:00',
                     DATE '2026-01-10', 502::BIGINT, 102::BIGINT,
                     'Bhopal', 'Indian', 1::BIGINT, 1::BIGINT,
                     300::BIGINT, 0::BIGINT, 30::BIGINT, 15::BIGINT,
                     -300::BIGINT, 'INR', 'UPI', 'Delivered',
                     4.0::DOUBLE, 30.0::DOUBLE)
                ) AS orders(
                    order_id, order_timestamp, order_date, user_id,
                    r_id, restaurant_city, cuisine, items_count,
                    sales_qty, subtotal, discount, delivery_fee, gst,
                    sales_amount, currency, payment_method, order_status,
                    customer_rating, delivery_time_min
                )
            ) TO '""" + str(source).replace("\\", "/") + """'
            (FORMAT PARQUET)
        """)

    with pytest.raises(RuntimeError, match="negative sales_amount"):
        run_pipeline(
            database,
            source,
            "2026-01-01",
            "2026-01-31",
        )

    with duckdb.connect(str(database), read_only=True) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM fact_orders"
        ).fetchone()[0]

    assert count == 0

def test_failed_file_records_pipeline_run_and_registry_status(tmp_path):
    import duckdb
    from src.incremental_pipeline import process_incoming_files

    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "broken.parquet"
    source.write_bytes(b"not a valid parquet file")

    database = tmp_path / "pipeline.duckdb"

    results = process_incoming_files(
        database,
        incoming,
        "2026-01-01",
        "2026-01-31",
    )

    assert len(results) == 1
    assert results[0]["status"] == "FAILED"

    with duckdb.connect(str(database), read_only=True) as con:
        run = con.execute("""
            SELECT status, error_message
            FROM pipeline_runs
            ORDER BY started_at DESC
            LIMIT 1
        """).fetchone()

        file_status = con.execute("""
            SELECT status, error_message
            FROM processed_files
            WHERE file_name = 'broken.parquet'
        """).fetchone()

    assert run is not None
    assert run[0] == "FAILED"
    assert run[1] is not None and run[1] != ""

    assert file_status is not None
    assert file_status[0] == "FAILED"
    assert file_status[1] is not None and file_status[1] != ""

