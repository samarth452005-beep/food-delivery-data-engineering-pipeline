

import streamlit as st
import pandas as pd
import plotly.express as px
from google.cloud import bigquery
from datetime import date

PROJECT_ID = "intrepid-charge-511709-t8"
TABLE_ID = f"{PROJECT_ID}.food_delivery.orders"

# The date range in the existing dashboard's source data.
DATA_MIN_DATE = date(2024, 1, 1)
DATA_MAX_DATE = date(2026, 6, 30)

st.set_page_config(
    page_title="Food Delivery Analytics",
    page_icon="🍽️",
    layout="wide",
)

st.title("🍽️ Food Delivery Analytics Dashboard")
st.caption("Historical business analytics | Google BigQuery")


@st.cache_resource
def get_client():
    # Uses the local Application Default Credentials configured with gcloud.
    # For deployment, configure credentials securely in the hosting platform.
    return bigquery.Client(project=PROJECT_ID)


@st.cache_data(ttl=3600, show_spinner=False)
def load_cities(project_id):
    client = get_client()
    query = f"""
        SELECT DISTINCT restaurant_city
        FROM `{project_id}.food_delivery.orders`
        WHERE restaurant_city IS NOT NULL
        ORDER BY restaurant_city
    """
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=5_000_000_000
    )
    return client.query(
        query, job_config=job_config
    ).to_dataframe()["restaurant_city"].tolist()


@st.cache_data(ttl=1800, show_spinner="Loading analytics from BigQuery...")
def load_analytics(project_id, start_date, end_date):
    client = get_client()

    query = f"""
        SELECT
            order_date,
            restaurant_city,
            COUNT(*) AS total_orders,
            COUNTIF(order_status = 'Delivered') AS delivered_orders,
            COUNTIF(order_status = 'Cancelled') AS cancelled_orders,
            COUNTIF(order_status = 'Refunded') AS refunded_orders,

            SUM(IF(
                order_status = 'Delivered',
                sales_amount, 0
            )) AS delivered_sales,

            SUM(IF(
                order_status = 'Delivered'
                AND delivery_time_min IS NOT NULL,
                delivery_time_min, 0
            )) AS delivered_minutes_sum,

            COUNTIF(
                order_status = 'Delivered'
                AND delivery_time_min IS NOT NULL
            ) AS delivery_time_count,

            SUM(IF(
                order_status = 'Delivered'
                AND customer_rating IS NOT NULL,
                customer_rating, 0
            )) AS rating_sum,

            COUNTIF(
                order_status = 'Delivered'
                AND customer_rating IS NOT NULL
            ) AS rating_count

        FROM `{project_id}.food_delivery.orders`
        WHERE order_date BETWEEN @start_date AND @end_date
        GROUP BY order_date, restaurant_city
    """

    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "start_date", "DATE", start_date
            ),
            bigquery.ScalarQueryParameter(
                "end_date", "DATE", end_date
            ),
        ],
        maximum_bytes_billed=5_000_000_000,
    )

    return client.query(
        query, job_config=config
    ).to_dataframe()


try:
    cities = load_cities(PROJECT_ID)
except Exception as exc:
    st.error("Could not load cities from BigQuery.")
    st.exception(exc)
    st.stop()


st.sidebar.header("Filters")

date_range = st.sidebar.date_input(
    "Order date range",
    value=(DATA_MIN_DATE, DATA_MAX_DATE),
    min_value=DATA_MIN_DATE,
    max_value=DATA_MAX_DATE,
)

if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
    st.info("Choose both a start date and an end date.")
    st.stop()

start_date, end_date = date_range

if start_date > end_date:
    st.error("Start date must not be after end date.")
    st.stop()

city = st.sidebar.selectbox("City", ["All cities"] + cities)

try:
    data = load_analytics(PROJECT_ID, start_date, end_date)
except Exception as exc:
    st.error("BigQuery could not load the analytics data.")
    st.exception(exc)
    st.stop()

if city != "All cities":
    data = data[data["restaurant_city"] == city]

if data.empty:
    st.warning("No records found for these filters.")
    st.stop()

# Keep calculations consistent with the original dashboard.
total_orders = int(data["total_orders"].sum())
delivered_orders = int(data["delivered_orders"].sum())
cancelled_orders = int(data["cancelled_orders"].sum())
refunded_orders = int(data["refunded_orders"].sum())
delivered_sales = float(data["delivered_sales"].sum())

aov = delivered_sales / delivered_orders if delivered_orders else 0
cancel_rate = (
    cancelled_orders / total_orders * 100 if total_orders else 0
)
refund_rate = (
    refunded_orders / total_orders * 100 if total_orders else 0
)

minutes_sum = data["delivered_minutes_sum"].sum()
minutes_count = data["delivery_time_count"].sum()
avg_delivery = minutes_sum / minutes_count if minutes_count else None

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
    f"{avg_delivery:.1f} min" if avg_delivery is not None else "N/A",
)
c8.metric(
    "Avg Customer Rating",
    f"{avg_rating:.2f} / 5" if avg_rating is not None else "N/A",
)

st.caption(
    "Delivered sales and average order value use delivered orders only. "
    "Cancellation and refund rates use all orders in the selection."
)
st.divider()

status_data = pd.DataFrame({
    "order_status": ["Delivered", "Cancelled", "Refunded"],
    "orders": [delivered_orders, cancelled_orders, refunded_orders],
})
status_data = status_data[status_data["orders"] > 0]

left, right = st.columns(2)

with left:
    st.subheader("Order Status Distribution")
    fig = px.pie(
        status_data,
        names="order_status",
        values="orders",
        hole=0.45,
    )
    st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("Monthly Delivered Sales")
    monthly = data.copy()
    monthly["month"] = (
        pd.to_datetime(monthly["order_date"])
        .dt.to_period("M")
        .dt.to_timestamp()
    )

    monthly = monthly.groupby("month", as_index=False).agg(
        total_orders=("total_orders", "sum"),
        delivered_orders=("delivered_orders", "sum"),
        delivered_sales=("delivered_sales", "sum"),
    ).sort_values("month")

    fig = px.line(
        monthly,
        x="month",
        y="delivered_sales",
        markers=True,
        labels={
            "month": "Month",
            "delivered_sales": "Delivered Sales (₹)",
        },
    )
    st.plotly_chart(fig, width="stretch")

st.subheader("Monthly Order Volume")
fig = px.bar(
    monthly,
    x="month",
    y="total_orders",
    labels={"month": "Month", "total_orders": "Orders"},
)
st.plotly_chart(fig, width="stretch")

st.divider()
st.subheader("City Performance")

city_data = data.groupby("restaurant_city", as_index=False).agg(
    total_orders=("total_orders", "sum"),
    delivered_orders=("delivered_orders", "sum"),
    cancelled_orders=("cancelled_orders", "sum"),
    refunded_orders=("refunded_orders", "sum"),
    delivered_sales=("delivered_sales", "sum"),
)

city_data["cancellation_rate_pct"] = (
    100 * city_data["cancelled_orders"]
    / city_data["total_orders"].where(city_data["total_orders"] != 0)
)
city_data["refund_rate_pct"] = (
    100 * city_data["refunded_orders"]
    / city_data["total_orders"].where(city_data["total_orders"] != 0)
)

top_cities = city_data.nlargest(
    15, "delivered_sales"
).sort_values("delivered_sales")

fig = px.bar(
    top_cities,
    x="delivered_sales",
    y="restaurant_city",
    orientation="h",
    title="Top 15 Cities by Delivered Sales",
    labels={
        "delivered_sales": "Delivered Sales (₹)",
        "restaurant_city": "City",
    },
    hover_data=["delivered_orders", "cancellation_rate_pct"],
)
st.plotly_chart(fig, width="stretch")

st.dataframe(
    city_data.sort_values("delivered_sales", ascending=False),
    width="stretch",
    hide_index=True,
)

st.download_button(
    "Download City Performance CSV",
    data=city_data.to_csv(index=False).encode("utf-8"),
    file_name="food_delivery_city_performance.csv",
    mime="text/csv",
)

st.caption(
    "Source: BigQuery historical orders. "
    "This dashboard reflects the selected historical date range, "
    "not live order events."
)
