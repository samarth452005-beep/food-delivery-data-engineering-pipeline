
import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from pathlib import Path

PROJECT = Path("/content/drive/MyDrive/food_delivery_project")
DB_PATH = PROJECT / "food_delivery.duckdb"

st.set_page_config(
    page_title="Food Delivery Analytics",
    page_icon="🍽️",
    layout="wide"
)

st.title("🍽️ Food Delivery Analytics Dashboard")
st.caption("Historical business analytics | DuckDB")

if not DB_PATH.exists():
    st.error("DuckDB database was not found.")
    st.stop()


@st.cache_data(show_spinner=False)
def load_filter_options(db_path, db_mtime):
    con = duckdb.connect(db_path, read_only=True)
    try:
        dates = con.execute("""
            SELECT MIN(order_date), MAX(order_date)
            FROM analytics_daily_city
        """).fetchone()

        cities = con.execute("""
            SELECT DISTINCT restaurant_city
            FROM analytics_daily_city
            WHERE restaurant_city IS NOT NULL
            ORDER BY restaurant_city
        """).fetchdf()["restaurant_city"].tolist()
        return dates[0], dates[1], cities
    finally:
        con.close()


@st.cache_data(show_spinner="Loading analytics...")
def load_analytics(db_path, db_mtime, start_date, end_date):
    con = duckdb.connect(db_path, read_only=True)
    try:
        return con.execute("""
            SELECT
                order_date,
                restaurant_city,
                total_orders,
                delivered_orders,
                cancelled_orders,
                refunded_orders,
                delivered_sales,
                delivered_minutes_sum,
                delivery_time_count,
                rating_sum,
                rating_count
            FROM analytics_daily_city
            WHERE order_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        """, [start_date, end_date]).df()
    finally:
        con.close()


db_mtime = DB_PATH.stat().st_mtime
min_date, max_date, cities = load_filter_options(
    str(DB_PATH), db_mtime
)

st.sidebar.header("Filters")
date_range = st.sidebar.date_input(
    "Order date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date
)

if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
    st.info("Choose both a start date and an end date.")
    st.stop()

start_date, end_date = date_range
if start_date > end_date:
    st.error("Start date must not be after end date.")
    st.stop()

city = st.sidebar.selectbox("City", ["All cities"] + cities)

data = load_analytics(
    str(DB_PATH), db_mtime, start_date, end_date
)

if city != "All cities":
    data = data[data["restaurant_city"] == city]

if data.empty:
    st.warning("No records found for these filters.")
    st.stop()

# Sum additive metrics; derive rates and averages from totals.
total_orders = int(data["total_orders"].sum())
delivered_orders = int(data["delivered_orders"].sum())
cancelled_orders = int(data["cancelled_orders"].sum())
refunded_orders = int(data["refunded_orders"].sum())
delivered_sales = float(data["delivered_sales"].sum())

aov = (
    delivered_sales / delivered_orders
    if delivered_orders else 0
)
cancel_rate = (
    cancelled_orders / total_orders * 100
    if total_orders else 0
)
refund_rate = (
    refunded_orders / total_orders * 100
    if total_orders else 0
)

minutes_sum = data["delivered_minutes_sum"].sum()
minutes_count = data["delivery_time_count"].sum()
avg_delivery = (
    minutes_sum / minutes_count if minutes_count else None
)

rating_sum = data["rating_sum"].sum()
rating_count = data["rating_count"].sum()
avg_rating = rating_sum / rating_count if rating_count else None

st.subheader(f"Business Overview: {start_date} to {end_date}")
st.caption(f"Selected city: {city}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Orders", f"{total_orders:,}")
c2.metric("Delivered Orders", f"{delivered_orders:,}")
c3.metric("Delivered Sales", f"₹{delivered_sales:,.0f}")
c4.metric("Average Order Value", f"₹{aov:,.2f}")

c5, c6, c7, c8 = st.columns(4)
c5.metric("Cancellation Rate", f"{cancel_rate:.2f}%")
c6.metric("Refund Rate", f"{refund_rate:.2f}%")
c7.metric(
    "Avg Delivery Time",
    f"{avg_delivery:.1f} min" if avg_delivery is not None else "N/A"
)
c8.metric(
    "Avg Customer Rating",
    f"{avg_rating:.2f} / 5" if avg_rating is not None else "N/A"
)

st.caption(
    "Delivered sales and average order value use delivered orders only. "
    "Cancellation and refund rates use all orders in the selection."
)
st.divider()

# Aggregate the filtered date-city rows by status.
status_data = pd.DataFrame({
    "order_status": ["Delivered", "Cancelled", "Refunded"],
    "orders": [
        delivered_orders, cancelled_orders, refunded_orders
    ]
})
status_data = status_data[status_data["orders"] > 0]

left, right = st.columns(2)

with left:
    st.subheader("Order Status Distribution")
    fig = px.pie(
        status_data,
        names="order_status",
        values="orders",
        hole=0.45
    )
    st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("Monthly Delivered Sales")
    monthly = data.copy()
    monthly["month"] = pd.to_datetime(
        monthly["order_date"]
    ).dt.to_period("M").dt.to_timestamp()

    monthly = monthly.groupby("month", as_index=False).agg(
        total_orders=("total_orders", "sum"),
        delivered_orders=("delivered_orders", "sum"),
        delivered_sales=("delivered_sales", "sum")
    ).sort_values("month")

    fig = px.line(
        monthly,
        x="month",
        y="delivered_sales",
        markers=True,
        labels={
            "month": "Month",
            "delivered_sales": "Delivered Sales (₹)"
        }
    )
    st.plotly_chart(fig, width="stretch")

st.subheader("Monthly Order Volume")
fig = px.bar(
    monthly,
    x="month",
    y="total_orders",
    labels={"month": "Month", "total_orders": "Orders"}
)
st.plotly_chart(fig, width="stretch")

st.divider()
st.subheader("City Performance")

city_data = data.groupby("restaurant_city", as_index=False).agg(
    total_orders=("total_orders", "sum"),
    delivered_orders=("delivered_orders", "sum"),
    cancelled_orders=("cancelled_orders", "sum"),
    refunded_orders=("refunded_orders", "sum"),
    delivered_sales=("delivered_sales", "sum")
)

city_data["cancellation_rate_pct"] = (
    100 * city_data["cancelled_orders"]
    / city_data["total_orders"].where(city_data["total_orders"] != 0)
)
city_data["refund_rate_pct"] = (
    100 * city_data["refunded_orders"]
    / city_data["total_orders"].where(city_data["total_orders"] != 0)
)

top_cities = city_data.nlargest(15, "delivered_sales").sort_values(
    "delivered_sales"
)

fig = px.bar(
    top_cities,
    x="delivered_sales",
    y="restaurant_city",
    orientation="h",
    title="Top 15 Cities by Delivered Sales",
    labels={
        "delivered_sales": "Delivered Sales (₹)",
        "restaurant_city": "City"
    },
    hover_data=["delivered_orders", "cancellation_rate_pct"]
)
st.plotly_chart(fig, width="stretch")

st.dataframe(
    city_data.sort_values("delivered_sales", ascending=False),
    width="stretch",
    hide_index=True
)

st.download_button(
    "Download City Performance CSV",
    data=city_data.to_csv(index=False).encode("utf-8"),
    file_name="food_delivery_city_performance.csv",
    mime="text/csv"
)

st.caption(
    "Source: analytics_daily_city, derived from historical orders. "
    "Data covers 2024-01-01 through 2026-06-30; this is not live order data."
)
