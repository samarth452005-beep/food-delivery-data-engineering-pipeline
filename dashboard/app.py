
import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from pathlib import Path

PROJECT_DIR = Path(
    "/content/drive/MyDrive/food_delivery_project"
)
DB_PATH = PROJECT_DIR / "food_delivery.duckdb"

st.set_page_config(
    page_title="Data Pipeline Monitor",
    page_icon="⚙️",
    layout="wide"
)

st.title("⚙️ Data Engineering Monitoring Dashboard")
st.caption("Food Delivery Pipeline | DuckDB | Streamlit")

if not DB_PATH.exists():
    st.error(f"DuckDB database not found: {DB_PATH}")
    st.stop()

con = duckdb.connect(str(DB_PATH), read_only=True)

try:
    runs = con.execute("""
        SELECT *
        FROM pipeline_runs
        ORDER BY started_at DESC
    """).df()

    quality = con.execute("""
        SELECT *
        FROM data_quality_results
        ORDER BY checked_at DESC
    """).df()

    total_rows = con.execute("""
        SELECT COUNT(*) FROM fact_orders
    """).fetchone()[0]

finally:
    con.close()

if runs.empty:
    st.warning("No pipeline runs found.")
    st.stop()

latest = runs.iloc[0]

# Summary metrics
total_runs = len(runs)
successful_runs = int((runs["status"] == "SUCCESS").sum())
failed_runs = int((runs["status"] == "FAILED").sum())

latest_quality = quality[
    quality["run_id"] == latest["run_id"]
] if not quality.empty else pd.DataFrame()

quality_pass = (
    int((latest_quality["status"] == "PASS").sum())
    if not latest_quality.empty else 0
)
quality_fail = (
    int((latest_quality["status"] == "FAIL").sum())
    if not latest_quality.empty else 0
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Pipeline Runs", f"{total_runs:,}")
c2.metric("Successful Runs", f"{successful_runs:,}")
c3.metric("Failed Runs", f"{failed_runs:,}")
c4.metric("Orders in Target", f"{total_rows:,}")

st.divider()

c5, c6, c7 = st.columns(3)
c5.metric("Latest Run Status", str(latest["status"]))
c6.metric("Latest Duration (sec)", f"{float(latest['duration_seconds']):.2f}")
c7.metric(
    "Latest Quality Checks",
    f"{quality_pass} passed / {quality_fail} failed"
)

st.subheader("Pipeline Run History")

history = runs.copy()
history["started_at"] = pd.to_datetime(
    history["started_at"], errors="coerce", utc=True
)
history["duration_seconds"] = pd.to_numeric(
    history["duration_seconds"], errors="coerce"
)
history = history.sort_values("started_at")

if not history["started_at"].isna().all():
    fig = px.line(
        history,
        x="started_at",
        y="duration_seconds",
        markers=True,
        title="Execution Duration Over Time",
        labels={
            "started_at": "Run Start",
            "duration_seconds": "Duration (seconds)"
        }
    )
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Recent Pipeline Runs")

run_columns = [
    c for c in [
        "run_id", "status", "started_at", "duration_seconds",
        "batch_start_date", "batch_end_date",
        "rows_processed", "rows_inserted_net", "error_message"
    ] if c in runs.columns
]
st.dataframe(
    runs[run_columns].head(50),
    use_container_width=True,
    hide_index=True
)

st.subheader("Latest Run: Data-Quality Checks")

if latest_quality.empty:
    st.info(
        "No quality results are associated with the latest run yet. "
        "Run the validation cell for that run."
    )
else:
    st.dataframe(
        latest_quality[
            [
                "check_name", "expected_value",
                "actual_value", "status", "checked_at"
            ]
        ],
        use_container_width=True,
        hide_index=True
    )

    st.progress(
        quality_pass / len(latest_quality),
        text=f"{quality_pass} of {len(latest_quality)} checks passed"
    )

st.subheader("Data-Quality History")

if quality.empty:
    st.info("No data-quality history is available.")
else:
    quality_summary = (
        quality.groupby(["run_id", "status"])
        .size()
        .reset_index(name="checks")
    )
    st.dataframe(
        quality_summary,
        use_container_width=True,
        hide_index=True
    )

st.caption(
    "Monitoring view only. This dashboard reads DuckDB and "
    "does not trigger or modify pipeline runs."
)
