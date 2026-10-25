
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from backend.main import app, UPLOAD_DIR

client = TestClient(app)


def create_test_dataset():
    """Create a small dataset for analytics tests."""
    dataset_id = "a" * 32

    df = pd.DataFrame(
        [
            {
                "order_id": 1,
                "quantity": 2,
                "unit_price": 100,
                "city": "Bhopal",
                "restaurant": "Spice Hub",
                "order_status": "Delivered",
            },
            {
                "order_id": 2,
                "quantity": 1,
                "unit_price": 50,
                "city": "Indore",
                "restaurant": "Pizza Point",
                "order_status": "Cancelled",
            },
        ]
    )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{dataset_id}.csv"
    df.to_csv(path, index=False)

    return dataset_id, path


def test_analytics_calculates_revenue():
    dataset_id, path = create_test_dataset()

    try:
        response = client.get(f"/analytics/{dataset_id}")

        assert response.status_code == 200

        result = response.json()
        assert result["total_rows"] == 2
        assert result["total_orders"] == 2
        assert result["delivered_orders"] == 1
        assert result["cancelled_orders"] == 1
        assert result["revenue"] == 250.0
        assert result["delivered_revenue"] == 200.0
        assert result["cancelled_revenue"] == 50.0

    finally:
        path.unlink(missing_ok=True)


def test_analytics_rejects_invalid_dataset_id():
    response = client.get("/analytics/not-a-valid-id")

    assert response.status_code == 400


def test_analytics_returns_404_for_missing_dataset():
    response = client.get(f"/analytics/{'b' * 32}")

    assert response.status_code == 404


def test_quality_detects_duplicate_rows():
    dataset_id = "c" * 32

    df = pd.DataFrame([
        {"order_id": 1, "quantity": 2, "unit_price": 100},
        {"order_id": 1, "quantity": 2, "unit_price": 100},
    ])

    path = UPLOAD_DIR / f"{dataset_id}.csv"
    df.to_csv(path, index=False)

    try:
        response = client.get(f"/quality/{dataset_id}")

        assert response.status_code == 200
        assert response.json()["duplicate_rows"] == 1
    finally:
        path.unlink(missing_ok=True)


def test_cleaning_removes_duplicate_rows():
    dataset_id = "d" * 32

    df = pd.DataFrame([
        {"order_id": 1, "quantity": 2, "unit_price": 100},
        {"order_id": 1, "quantity": 2, "unit_price": 100},
    ])

    path = UPLOAD_DIR / f"{dataset_id}.csv"
    df.to_csv(path, index=False)

    try:
        response = client.post(
            f"/clean/{dataset_id}",
            json={
                "remove_duplicates": True,
                "normalize_categories": True,
                "missing_values": "keep",
                "invalid_numeric_values": "keep",
            },
        )

        assert response.status_code == 200

        result = response.json()
        assert result["original_rows"] == 2
        assert result["cleaned_rows"] == 1
        assert result["rows_removed"] == 1

        cleaned_id = result["cleaned_id"]
        cleaned_path = UPLOAD_DIR / f"{cleaned_id}.csv"

        try:
            cleaned_df = pd.read_csv(cleaned_path)
            assert len(cleaned_df) == 1
        finally:
            cleaned_path.unlink(missing_ok=True)

    finally:
        path.unlink(missing_ok=True)
