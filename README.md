# Food Delivery End-to-End Data Engineering Project

An end-to-end portfolio project that transforms food delivery
order data into analytics-ready datasets, validates data quality,
and presents business insights through interactive dashboards.

## 🚀 Live Demo

**[Open Food Delivery Analytics Dashboard](https://food-delivery-data-engineering-pipeline-fc5bszgrowqw4cotdmghtz.streamlit.app/)**

Explore interactive KPIs, city filters, daily order trends, cancellation and refund rates, and delivery performance.

> **Note:** The publicly deployed dashboard uses synthetic demonstration data. The full data engineering pipeline and cloud components are documented separately in this repository.


## Project Goals

- Process a large historical food delivery dataset.
- Store data in efficient Parquet format.
- Build analytical SQL views in BigQuery Sandbox.
- Develop an incremental upsert prototype using DuckDB.
- Validate data quality and maintain pipeline run history.
- Build separate business analytics and pipeline monitoring dashboards.

## Architecture

```text
Historical Food Delivery Data
            |
            v
     CSV to Parquet
            |
            +---------------------> Private AWS S3
            |
            v
   BigQuery Sandbox
   SQL Analytics Views
            |
            +----> Business Analytics (SQL views)
            |
            v
      DuckDB Processing
      Incremental Upsert
            |
            +----> Pipeline Run History
            |
            +----> Data Quality Results
            |
            +----> Streamlit Dashboards
                    |             |
                    v             v
               Pipeline       Food Delivery
               Monitoring     Analytics
```

Note: The local DuckDB incremental pipeline is a prototype.
BigQuery Sandbox is used for read-only analytics because
the project intentionally avoids enabling billing.

## Technology Stack

- Python
- Pandas and PyArrow
- DuckDB
- Apache Parquet
- Google Colab and Google Drive
- AWS S3
- Google BigQuery Sandbox
- Streamlit
- Plotly
- SQL

## Dataset

The historical dataset contains 10,000,000 orders covering
2024-01-01 through 2026-06-30, along with related food,
menu, restaurant, order-item, review, and user tables.

The orders dataset has three observed statuses:

- Delivered
- Cancelled
- Refunded

The source data was converted to compressed Parquet files.
The source dataset is historical, not a live order feed.

## Data Engineering Features

### Storage and processing
- Converted CSV data into Parquet.
- Stored processed Parquet data in a private AWS S3 bucket.
- Loaded analytical tables into BigQuery Sandbox.
- Used DuckDB for local incremental processing.

### Incremental processing prototype
- Uses `order_id` as the target table key.
- Supports upserts for a selected order-date batch.
- Records execution status, duration, and row counts.
- Tested rerunning the same batch without increasing the target row count.

### Data quality
The current target-batch validation checks:
- Null order IDs
- Duplicate order IDs
- Null order dates or statuses
- Negative sales amounts
- Expected batch row count

All five checks passed for the validated batch of 110,423 orders.

### Analytics
- Delivered sales and average order value
- Order status distribution
- Cancellation and refund rates
- Monthly sales and order trends
- City-level sales and cancellation analysis
- Delivery duration and customer ratings

### Monitoring
- Pipeline run history
- Success and failure counts
- Processing duration
- Rows processed and inserted
- Persisted data-quality check results

## Dashboards

### Food Delivery Analytics
Interactive date and city filters, KPI cards, order status
distribution, monthly trends, city comparisons, and CSV export.

### Data Engineering Monitoring
Pipeline status, execution history, target row count, and
data-quality results.

Both dashboards currently run in the Google Colab development
environment. They are not permanently hosted services.

## Reproducing the Project

1. Open the project notebook in Google Colab.
2. Mount Google Drive and install the required Python packages.
3. Ensure the Parquet source files are available in the `parquet/` folder.
4. Run the data-quality and DuckDB pipeline steps.
5. Start the required Streamlit dashboard.

The dashboards currently use paths under:
`/content/drive/MyDrive/food_delivery_project`

These paths must be adjusted for another environment.

## Current Limitations

- The incremental DuckDB pipeline processes a selected date range.
- The current prototype rewrites matching rows during upserts.
- Automated scheduling and production orchestration are not yet implemented.
- The dashboards depend on the Colab runtime and Google Drive.
- The source data is historical rather than continuously ingested.
- BigQuery Sandbox is used without enabling billing.

## Future Improvements

- Add automated pipeline execution and scheduling.
- Add reusable automated data-quality tests.
- Optimize incremental processing to update only changed records.
- Add pipeline failure handling and retry logic.
- Deploy the dashboards to a persistent hosting environment.
- Add CI/testing and improve repository documentation.

## Security

Do not commit cloud credentials, API keys, passwords,
personal customer data, or service-account JSON files.
Keep the AWS bucket private and use appropriate access controls.

## Author

Samarth Sharma

Data Engineering Portfolio Project
