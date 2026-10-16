import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="Food Delivery Analytics Demo",
                   page_icon="🍱", layout="wide")

st.title("🍱 Food Delivery Analytics")
st.caption("Interactive demo using synthetic data — not production data.")

rng = np.random.default_rng(42)
dates = pd.date_range("2026-01-01", periods=180, freq="D")
cities = ["Jabalpur", "Indore", "Bhopal", "Pune", "Jaipur"]

df = pd.DataFrame({
    "date": rng.choice(dates, 3000),
    "city": rng.choice(cities, 3000),
    "status": rng.choice(
        ["Delivered", "Cancelled", "Refunded"],
        3000, p=[0.915, 0.06, 0.025]
    ),
    "sales": rng.integers(180, 1500, 3000),
    "delivery_minutes": rng.normal(32, 8, 3000).clip(10, 75).round(1),
    "rating": rng.normal(4.1, 0.6, 3000).clip(1, 5).round(1),
})

st.info("All figures are generated sample data for demonstration.")

selected_cities = st.multiselect(
    "Filter cities", cities, default=cities
)
filtered = df[df["city"].isin(selected_cities)].copy()

if filtered.empty:
    st.warning("Select at least one city.")
    st.stop()

delivered = filtered[filtered["status"] == "Delivered"]
total = len(filtered)
sales = delivered["sales"].sum()
aov = delivered["sales"].mean() if not delivered.empty else 0
cancel_rate = (filtered["status"] == "Cancelled").mean() * 100
refund_rate = (filtered["status"] == "Refunded").mean() * 100

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total orders", f"{total:,}")
c2.metric("Delivered sales", f"₹{sales:,.0f}")
c3.metric("Cancellation rate", f"{cancel_rate:.1f}%")
c4.metric("Refund rate", f"{refund_rate:.1f}%")

st.subheader("Daily order volume")
daily = filtered.groupby("date").size().sort_index()
st.line_chart(daily)

st.subheader("Orders by city")
city_counts = filtered.groupby("city").size().sort_values(ascending=False)
st.bar_chart(city_counts)

st.subheader("Order status")
status_counts = filtered["status"].value_counts()
st.bar_chart(status_counts)

st.subheader("Delivery performance by city")
performance = filtered.groupby("city").agg(
    orders=("status", "size"),
    avg_delivery_minutes=("delivery_minutes", "mean"),
    avg_rating=("rating", "mean"),
).round(2)
st.dataframe(performance, use_container_width=True)

st.download_button(
    "Download demo data as CSV",
    data=filtered.to_csv(index=False).encode("utf-8"),
    file_name="food_delivery_demo.csv",
    mime="text/csv",
)
