
from typing import Literal

from fastapi import Body
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile

app = FastAPI(title="Food Delivery Analytics API")

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def read_dataset(path: Path) -> pd.DataFrame:
    """Read a supported dataset from disk."""
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise ValueError("Unsupported file format")


@app.get("/")
def home():
    return {"message": "Food Delivery Analytics API is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()

    if extension not in {".csv", ".parquet"}:
        await file.close()
        raise HTTPException(
            status_code=400,
            detail="Only CSV and Parquet files are supported.",
        )

    dataset_id = uuid4().hex
    saved_path = UPLOAD_DIR / f"{dataset_id}{extension}"
    size = 0

    try:
        with saved_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)

                if size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="File exceeds the 100 MB upload limit.",
                    )

                destination.write(chunk)

        # Limit the initial CSV preview for responsiveness.
        if extension == ".csv":
            df = pd.read_csv(saved_path, nrows=10)
        else:
            df = pd.read_parquet(saved_path).head(10)

        return {
            "dataset_id": dataset_id,
            "message": "Dataset uploaded successfully",
            "filename": filename,
            "size_bytes": size,
            "preview_rows": len(df),
            "columns": df.columns.tolist(),
            "dtypes": {
                column: str(dtype)
                for column, dtype in df.dtypes.items()
            },
            "preview": df.fillna("").to_dict(orient="records"),
        }

    except HTTPException:
        saved_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Could not read dataset. Check that the file is valid: {exc}",
        ) from exc
    finally:
        await file.close()



@app.get("/quality/{dataset_id}")
def analyze_data_quality(dataset_id: str):
    if (
        len(dataset_id) != 32
        or any(c not in "0123456789abcdef" for c in dataset_id)
    ):
        raise HTTPException(status_code=400, detail="Invalid dataset ID.")

    matches = [
        UPLOAD_DIR / f"{dataset_id}{ext}"
        for ext in (".csv", ".parquet")
        if (UPLOAD_DIR / f"{dataset_id}{ext}").is_file()
    ]

    if not matches:
        raise HTTPException(
            status_code=404,
            detail="Dataset not found. Please upload it again.",
        )

    try:
        df = read_dataset(matches[0])
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read dataset: {exc}",
        ) from exc

    missing_values = {
        column: int(count)
        for column, count in df.isna().sum().items()
        if count > 0
    }

    duplicate_rows = int(df.duplicated().sum())
    invalid_values = {}
    inconsistent_categories = {}
    row_issues = []

    # Collect issues for each record without changing the data.
    for index, row in df.iterrows():
        issues = []

        for column in df.columns:
            if pd.isna(row[column]):
                issues.append(f"Missing value: {column}")

        if "quantity" in df.columns:
            quantity = pd.to_numeric(
                pd.Series([row["quantity"]]), errors="coerce"
            ).iloc[0]

            if pd.notna(quantity) and quantity <= 0:
                issues.append("Quantity must be greater than zero")

        if "unit_price" in df.columns:
            price = pd.to_numeric(
                pd.Series([row["unit_price"]]), errors="coerce"
            ).iloc[0]

            if pd.notna(price) and price < 0:
                issues.append("Unit price cannot be negative")

        if df.iloc[:index].shape[0] > 0 and row.equals(df.iloc[:index].iloc[-1]):
            pass  # Duplicate detection is handled below.

        if issues:
            row_issues.append({
                "row_number": int(index) + 2,
                "order_id": (
                    str(row["order_id"])
                    if "order_id" in df.columns
                    and pd.notna(row["order_id"])
                    else None
                ),
                "issues": issues,
            })

    # Add exact duplicates, marking every occurrence after the first.
    duplicate_mask = df.duplicated()
    for index in df.index[duplicate_mask]:
        matching = next(
            (
                item for item in row_issues
                if item["row_number"] == int(index) + 2
            ),
            None,
        )

        if matching:
            matching["issues"].append("Exact duplicate row")
        else:
            row_issues.append({
                "row_number": int(index) + 2,
                "order_id": (
                    str(df.at[index, "order_id"])
                    if "order_id" in df.columns
                    and pd.notna(df.at[index, "order_id"])
                    else None
                ),
                "issues": ["Exact duplicate row"],
            })

    if "quantity" in df.columns:
        quantity = pd.to_numeric(df["quantity"], errors="coerce")
        count = int((quantity <= 0).sum())
        if count:
            invalid_values["quantity <= 0"] = count

    if "unit_price" in df.columns:
        price = pd.to_numeric(df["unit_price"], errors="coerce")
        count = int((price < 0).sum())
        if count:
            invalid_values["unit_price < 0"] = count

    for column in ("order_status", "city", "restaurant"):
        if column not in df.columns:
            continue

        groups = {}
        for value in df[column].dropna().astype(str).unique():
            groups.setdefault(value.strip().casefold(), []).append(value)

        inconsistent = {
            key: variants
            for key, variants in groups.items()
            if len(variants) > 1
        }

        if inconsistent:
            inconsistent_categories[column] = inconsistent

    row_issues.sort(key=lambda item: item["row_number"])

    return {
        "dataset_id": dataset_id,
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "missing_values": missing_values,
        "duplicate_rows": duplicate_rows,
        "invalid_values": invalid_values,
        "inconsistent_categories": inconsistent_categories,
        "row_issues": row_issues,
        "rows_with_issues": len(row_issues),
        "note": "Analysis only: no data was changed or deleted.",
    }


class CleaningOptions(BaseModel):
    remove_duplicates: bool = True
    normalize_categories: bool = True
    missing_values: Literal["keep", "drop_rows"] = "keep"
    invalid_numeric_values: Literal["keep", "replace_with_null"] = "keep"


@app.post("/clean/{dataset_id}")
def clean_dataset(
    dataset_id: str,
    options: CleaningOptions = Body(...),
):
    # Validate the uploaded dataset ID.
    if (
        len(dataset_id) != 32
        or any(c not in "0123456789abcdef" for c in dataset_id)
    ):
        raise HTTPException(status_code=400, detail="Invalid dataset ID.")

    source_files = [
        UPLOAD_DIR / f"{dataset_id}{ext}"
        for ext in (".csv", ".parquet")
        if (UPLOAD_DIR / f"{dataset_id}{ext}").is_file()
    ]

    if not source_files:
        raise HTTPException(
            status_code=404,
            detail="Dataset not found. Please upload it again.",
        )

    source_path = source_files[0]

    try:
        df = read_dataset(source_path)
        original_rows = len(df)
        changes = []

        # 1. Remove exact duplicate rows only if selected.
        if options.remove_duplicates:
            before = len(df)
            df = df.drop_duplicates().copy()
            removed = before - len(df)
            if removed:
                changes.append(f"Removed {removed} exact duplicate row(s).")

        # 2. Handle invalid numeric values in known columns.
        if options.invalid_numeric_values == "replace_with_null":
            for column, invalid_condition in (
                ("quantity", lambda s: s <= 0),
                ("unit_price", lambda s: s < 0),
            ):
                if column in df.columns:
                    numeric = pd.to_numeric(df[column], errors="coerce")
                    invalid_mask = numeric.notna() & invalid_condition(numeric)

                    count = int(invalid_mask.sum())
                    if count:
                        df.loc[invalid_mask, column] = None
                        changes.append(
                            f"Replaced {count} invalid value(s) in "
                            f"'{column}' with missing values."
                        )

        # 3. Normalize categories without changing their meaning.
        if options.normalize_categories:
            for column in ("order_status", "city", "restaurant"):
                if column not in df.columns:
                    continue

                non_null = df[column].dropna().astype(str)
                canonical = {}

                for value in non_null:
                    cleaned = value.strip()
                    canonical.setdefault(cleaned.casefold(), cleaned)

                # Prefer title case for order statuses; preserve the
                # first cleaned spelling for cities and restaurant names.
                if column == "order_status":
                    canonical = {
                        key: key.title() for key in canonical
                    }

                before_values = df[column].copy()
                df[column] = df[column].map(
                    lambda value: (
                        canonical.get(str(value).strip().casefold(),
                                      str(value).strip())
                        if pd.notna(value)
                        else value
                    )
                )

                changed = int(
                    (before_values.fillna("__NULL__").astype(str)
                     != df[column].fillna("__NULL__").astype(str)).sum()
                )
                if changed:
                    changes.append(
                        f"Standardized {changed} value(s) in '{column}'."
                    )

        # 4. Missing-value policy is explicit; no filling is guessed.
        if options.missing_values == "drop_rows":
            before = len(df)
            df = df.dropna().copy()
            removed = before - len(df)
            if removed:
                changes.append(
                    f"Removed {removed} row(s) containing missing values."
                )

        # Save a new output; never overwrite the uploaded original.
        cleaned_id = uuid4().hex
        extension = source_path.suffix.lower()
        output_path = UPLOAD_DIR / f"{cleaned_id}{extension}"

        if extension == ".csv":
            df.to_csv(output_path, index=False)
        else:
            df.to_parquet(output_path, index=False)

        return {
            "cleaned_id": cleaned_id,
            "original_rows": original_rows,
            "cleaned_rows": len(df),
            "rows_removed": original_rows - len(df),
            "columns": df.columns.tolist(),
            "changes": changes,
            "missing_values_remaining": {
                column: int(count)
                for column, count in df.isna().sum().items()
                if count > 0
            },
            "download_url": f"/download/{cleaned_id}",
            "message": "Cleaning completed. The original file was preserved.",
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not clean dataset: {exc}",
        ) from exc


@app.get("/download/{cleaned_id}")
def download_cleaned_dataset(cleaned_id: str):
    if (
        len(cleaned_id) != 32
        or any(c not in "0123456789abcdef" for c in cleaned_id)
    ):
        raise HTTPException(status_code=400, detail="Invalid dataset ID.")

    matches = [
        UPLOAD_DIR / f"{cleaned_id}{ext}"
        for ext in (".csv", ".parquet")
        if (UPLOAD_DIR / f"{cleaned_id}{ext}").is_file()
    ]

    if not matches:
        raise HTTPException(status_code=404, detail="Cleaned file not found.")

    path = matches[0]
    return FileResponse(
        path=path,
        filename=f"cleaned_dataset{path.suffix}",
        media_type=(
            "text/csv"
            if path.suffix == ".csv"
            else "application/octet-stream"
        ),
    )


@app.get("/analytics/{dataset_id}")
def generate_analytics(dataset_id: str):
    if (
        len(dataset_id) != 32
        or any(c not in "0123456789abcdef" for c in dataset_id)
    ):
        raise HTTPException(status_code=400, detail="Invalid dataset ID.")

    matches = [
        UPLOAD_DIR / f"{dataset_id}{ext}"
        for ext in (".csv", ".parquet")
        if (UPLOAD_DIR / f"{dataset_id}{ext}").is_file()
    ]

    if not matches:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    try:
        df = read_dataset(matches[0])
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read dataset: {exc}",
        ) from exc

    total_rows = len(df)

    total_orders = (
        int(df["order_id"].nunique())
        if "order_id" in df.columns
        else total_rows
    )

    # Normalize statuses for consistent counting.
    if "order_status" in df.columns:
        status = (
            df["order_status"]
            .astype("string")
            .str.strip()
            .str.casefold()
        )
        orders_by_status = {
            str(key).title(): int(value)
            for key, value in (
                status.fillna("missing")
                .value_counts()
                .items()
            )
        }
        delivered_orders = int((status == "delivered").sum())
        cancelled_orders = int((status == "cancelled").sum())
    else:
        status = pd.Series("unknown", index=df.index, dtype="string")
        orders_by_status = {}
        delivered_orders = 0
        cancelled_orders = 0

    # Initialize every returned metric so all response fields exist.
    revenue = None
    delivered_revenue = None
    cancelled_revenue = None
    revenue_by_city = {}
    top_restaurants = {}

    has_revenue_columns = {
        "quantity", "unit_price"
    }.issubset(df.columns)

    if has_revenue_columns:
        quantity = pd.to_numeric(df["quantity"], errors="coerce")
        price = pd.to_numeric(df["unit_price"], errors="coerce")

        valid = (
            quantity.notna()
            & price.notna()
            & (quantity > 0)
            & (price >= 0)
        )

        row_revenue = quantity * price
        revenue = round(float(row_revenue[valid].sum()), 2)

        if "order_status" in df.columns:
            delivered_mask = valid & (status == "delivered")
            cancelled_mask = valid & (status == "cancelled")

            delivered_revenue = round(
                float(row_revenue[delivered_mask].sum()), 2
            )
            cancelled_revenue = round(
                float(row_revenue[cancelled_mask].sum()), 2
            )

        # Revenue by city.
        if "city" in df.columns:
            city_values = df["city"].astype("string").str.strip()
            city_valid = valid & city_values.notna() & (city_values != "")

            city_frame = pd.DataFrame({
                "city": city_values[city_valid],
                "revenue": row_revenue[city_valid],
            })

            revenue_by_city = {
                str(key): round(float(value), 2)
                for key, value in (
                    city_frame.groupby("city")["revenue"]
                    .sum()
                    .sort_values(ascending=False)
                    .items()
                )
            }

        # Top five restaurants by revenue.
        if "restaurant" in df.columns:
            restaurant_values = (
                df["restaurant"].astype("string").str.strip()
            )
            restaurant_valid = (
                valid
                & restaurant_values.notna()
                & (restaurant_values != "")
            )

            restaurant_frame = pd.DataFrame({
                "restaurant": restaurant_values[restaurant_valid],
                "revenue": row_revenue[restaurant_valid],
            })

            top_restaurants = {
                str(key): round(float(value), 2)
                for key, value in (
                    restaurant_frame.groupby("restaurant")["revenue"]
                    .sum()
                    .nlargest(5)
                    .items()
                )
            }

    return {
        "dataset_id": dataset_id,
        "total_rows": total_rows,
        "total_orders": total_orders,
        "delivered_orders": delivered_orders,
        "cancelled_orders": cancelled_orders,
        "revenue": revenue,
        "delivered_revenue": delivered_revenue,
        "cancelled_revenue": cancelled_revenue,
        "orders_by_status": orders_by_status,
        "revenue_by_city": revenue_by_city,
        "top_restaurants_by_revenue": top_restaurants,
        "revenue_note": (
            "Revenue is quantity × unit_price for records with valid "
            "positive quantities and nonnegative prices. Delivered and "
            "cancelled revenue are separated by order status."
        ),
    }

