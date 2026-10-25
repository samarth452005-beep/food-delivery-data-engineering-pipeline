
import os
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="Data Pipeline Monitor",
    page_icon="⚙️",
    layout="wide",
)

st.title("⚙️ Data Engineering Monitoring Dashboard")
st.caption("Food Delivery Pipeline | Airflow | DuckDB")

# Override with FOOD_DELIVERY_DB when deploying.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(
    os.getenv(
        "FOOD_DELIVERY_DB",
        str(PROJECT_ROOT / "data" / "automation.duckdb"),
    )
)

if not DB_PATH.exists():
    st.error(f"DuckDB database not found: {DB_PATH}")
    st.info(
        "Set FOOD_DELIVERY_DB to the path of your pipeline database."
    )
    st.stop()


@st.cache_data(show_spinner="Loading pipeline monitoring data...")
def load_monitoring_data(db_path: str, db_mtime: float):
    con = duckdb.connect(db_path, read_only=True)
    try:
        tables = {
            row[0]
            for row in con.execute("SHOW TABLES").fetchall()
        }

        runs = (
            con.execute(
                "SELECT * FROM pipeline_runs ORDER BY started_at DESC"
            ).df()
            if "pipeline_runs" in tables
            else pd.DataFrame()
        )

        files = (
            con.execute(
                "SELECT * FROM processed_files ORDER BY discovered_at DESC"
            ).df()
            if "processed_files" in tables
            else pd.DataFrame()
        )

        total_orders = (
            con.execute("SELECT COUNT(*) FROM fact_orders").fetchone()[0]
            if "fact_orders" in tables
            else 0
        )

        quality = (
            con.execute(
                "SELECT * FROM data_quality_results ORDER BY checked_at DESC"
            ).df()
            if "data_quality_results" in tables
            else pd.DataFrame()
        )

        return runs, files, total_orders, quality, sorted(tables)
    finally:
        con.close()


runs, files, total_orders, quality, tables = load_monitoring_data(
    str(DB_PATH), DB_PATH.stat().st_mtime
)

st.caption(f"Database: {DB_PATH.name}")
st.caption(f"Available tables: {', '.join(tables) or 'None'}")

if runs.empty:
    st.warning("No pipeline runs are available in this database.")
    st.stop()

runs["started_at"] = pd.to_datetime(
    runs["started_at"], errors="coerce", utc=True
)
runs["duration_seconds"] = pd.to_numeric(
    runs["duration_seconds"], errors="coerce"
)
runs = runs.sort_values("started_at", ascending=False)

successful_runs = int((runs["status"] == "SUCCESS").sum())
failed_runs = int((runs["status"] == "FAILED").sum())
latest = runs.iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Pipeline Runs", f"{len(runs):,}")
c2.metric("Successful Runs", f"{successful_runs:,}")
c3.metric("Failed Runs", f"{failed_runs:,}")
c4.metric("Orders in Target", f"{total_orders:,}")

st.divider()

c5, c6, c7 = st.columns(3)
c5.metric("Latest Run Status", str(latest["status"]))

duration = latest.get("duration_seconds")
c6.metric(
    "Latest Duration",
    f"{float(duration):.2f} sec"
    if pd.notna(duration)
    else "N/A",
)

c7.metric("Registered Files", f"{len(files):,}")

if not runs["started_at"].isna().all():
    history = runs.dropna(subset=["started_at"]).sort_values("started_at")
    st.subheader("Pipeline Run History")

    fig = px.line(
        history,
        x="started_at",
        y="duration_seconds",
        color="status" if "status" in history.columns else None,
        markers=True,
        title="Execution Duration Over Time",
        labels={
            "started_at": "Run Start",
            "duration_seconds": "Duration (seconds)",
        },
    )
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Recent Pipeline Runs")

run_columns = [
    c for c in [
        "run_id",
        "source_file",
        "status",
        "started_at",
        "finished_at",
        "duration_seconds",
        "batch_start_date",
        "batch_end_date",
        "rows_processed",
        "rows_inserted",
        "rows_updated",
        "rows_inserted_net",
        "error_message",
    ]
    if c in runs.columns
]
st.dataframe(runs[run_columns].head(50), use_container_width=True, hide_index=True)

st.subheader("Incoming File Registry")

if files.empty:
    st.info("No incoming files have been registered yet.")
else:
    if "status" in files.columns:
        counts = (
            files["status"]
            .value_counts()
            .rename_axis("status")
            .reset_index(name="files")
        )
        st.plotly_chart(
            px.bar(counts, x="status", y="files", title="File Processing Status"),
            use_container_width=True,
        )

    file_columns = [
        c for c in [
            "file_name",
            "status",
            "discovered_at",
            "processed_at",
            "error_message",
        ]
        if c in files.columns
    ]
    st.dataframe(files[file_columns], use_container_width=True, hide_index=True)

st.subheader("Data-Quality Checks")

if quality.empty:
    st.info(
        "No data-quality results table is available in this database yet. "
        "Pipeline run failures and file errors are shown above."
    )
else:
    latest_quality = quality[
        quality["run_id"] == latest["run_id"]
    ] if "run_id" in quality.columns else pd.DataFrame()

    if latest_quality.empty:
        st.info("No quality checks are associated with the latest run.")
    else:
        st.dataframe(latest_quality, use_container_width=True, hide_index=True)

    st.dataframe(quality.head(100), use_container_width=True, hide_index=True)

st.caption(
    "Read-only monitoring dashboard. Refresh the page to load the latest "
    "pipeline status. This page does not trigger or modify pipeline runs."
)
