
import requests
import streamlit as st
import pandas as pd
import os

API_URL = os.getenv(
    "API_URL",
    "https://food-delivery-analytics-api.onrender.com",
).rstrip("/")

st.set_page_config(
    page_title="Food Delivery Analytics",
    page_icon="🍽️",
    layout="wide",
)

st.title("Food Delivery Analytics Platform")
st.write("Upload, inspect, and assess the quality of your datasets.")

if "dataset_id" not in st.session_state:
    st.session_state.dataset_id = None

uploaded_file = st.file_uploader(
    "Choose a CSV or Parquet dataset",
    type=["csv", "parquet"],
)

if uploaded_file is not None:
    st.caption(
        f"Selected: {uploaded_file.name} "
        f"({uploaded_file.size / (1024 * 1024):.3f} MB)"
    )

    if st.button("Upload and Preview Dataset", type="primary"):
        try:
            with st.spinner("Uploading dataset..."):
                response = requests.post(
                    f"{API_URL}/upload",
                    files={
                        "file": (
                            uploaded_file.name,
                            uploaded_file.getvalue(),
                            "application/octet-stream",
                        )
                    },
                    timeout=120,
                )

            response.raise_for_status()
            result = response.json()

            st.session_state.dataset_id = result["dataset_id"]
            st.success(result["message"])

            st.subheader("Dataset information")
            col1, col2 = st.columns(2)
            col1.metric("Preview rows", result["preview_rows"])
            col2.metric("Number of columns", len(result["columns"]))

            st.write("**Column names**")
            st.write(result["columns"])

            st.write("**Data types**")
            st.json(result["dtypes"])

            st.subheader("First 10 rows")
            st.dataframe(result["preview"], use_container_width=True)

        except requests.RequestException as exc:
            st.error(f"Upload failed: {exc}")
        except (KeyError, ValueError) as exc:
            st.error(f"Unexpected backend response: {exc}")

if st.session_state.dataset_id:
    st.divider()
    st.subheader("Data Quality Analysis")
    st.write(
        "Check missing values, duplicate rows, invalid values, "
        "and inconsistent categories."
    )

    if st.button("Analyze Data Quality"):
        try:
            with st.spinner("Analyzing the complete dataset..."):
                response = requests.get(
                    f"{API_URL}/quality/{st.session_state.dataset_id}",
                    timeout=120,
                )

            response.raise_for_status()
            report = response.json()

            st.success("Data quality analysis completed.")

            col1, col2, col3 = st.columns(3)
            col1.metric("Total rows", report["total_rows"])
            col2.metric("Total columns", report["total_columns"])
            col3.metric("Exact duplicate rows", report["duplicate_rows"])

            st.subheader("Missing values")
            if report["missing_values"]:
                missing_df = [
                    {"Column": col, "Missing values": count}
                    for col, count in report["missing_values"].items()
                ]
                st.dataframe(missing_df, use_container_width=True)
            else:
                st.success("No missing values detected.")

            st.subheader("Invalid values")
            if report["invalid_values"]:
                st.json(report["invalid_values"])
            else:
                st.success("No configured invalid values detected.")

            st.subheader("Inconsistent categories")
            if report["inconsistent_categories"]:
                st.json(report["inconsistent_categories"])
            else:
                st.success(
                    "No capitalization or whitespace inconsistencies "
                    "detected in the checked columns."
                )

            st.info(report["note"])
            
            st.subheader("Rows requiring review")

            row_issues = report.get("row_issues", [])

            if row_issues:
                st.warning(
                    f"{report['rows_with_issues']} row(s) "
                    "have one or more detected issues."
                )

                issue_rows = [
                    {
                        "CSV row number": item["row_number"],
                        "Order ID": item["order_id"] or "Missing",
                        "Issues": "; ".join(item["issues"]),
                    }
                    for item in row_issues
                ]

                st.dataframe(
                    issue_rows,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.success("No row-level issues detected.")


        except requests.RequestException as exc:
            st.error(f"Quality analysis failed: {exc}")

st.divider()
st.subheader("Data Cleaning")

st.write(
    "Choose the cleaning rules you want to apply. "
    "The uploaded original will not be overwritten."
)

if not st.session_state.get("dataset_id"):
    st.info("Upload a dataset first to enable cleaning.")
else:
    remove_duplicates = st.checkbox(
        "Remove exact duplicate rows",
        value=True,
    )

    normalize_categories = st.checkbox(
        "Standardize category capitalization and whitespace",
        value=True,
    )

    missing_values = st.selectbox(
        "How should rows with missing values be handled?",
        options=["Keep rows", "Drop rows containing missing values"],
        index=0,
    )

    invalid_values = st.selectbox(
        "How should invalid quantities and prices be handled?",
        options=[
            "Keep invalid values for review",
            "Replace invalid values with missing values",
        ],
        index=0,
    )

    if st.button("Apply Selected Cleaning Rules", type="primary"):
        options = {
            "remove_duplicates": remove_duplicates,
            "normalize_categories": normalize_categories,
            "missing_values": (
                "drop_rows"
                if missing_values == "Drop rows containing missing values"
                else "keep"
            ),
            "invalid_numeric_values": (
                "replace_with_null"
                if invalid_values
                == "Replace invalid values with missing values"
                else "keep"
            ),
        }

        try:
            with st.spinner("Applying selected cleaning rules..."):
                response = requests.post(
                    f"{API_URL}/clean/"
                    f"{st.session_state.dataset_id}",
                    json=options,
                    timeout=120,
                )

            response.raise_for_status()
            result = response.json()

            st.session_state.cleaned_id = result["cleaned_id"]
            st.session_state.cleaning_report = result

            st.success(result["message"])

        except requests.RequestException as exc:
            st.error(f"Cleaning failed: {exc}")

    report = st.session_state.get("cleaning_report")

    
report = st.session_state.get("cleaning_report")


if report:
    st.subheader("Cleaning summary")

    col1, col2, col3 = st.columns(3)
    col1.metric("Original rows", report["original_rows"])
    col2.metric("Cleaned rows", report["cleaned_rows"])
    col3.metric("Rows removed", report["rows_removed"])

    st.write("**Changes applied**")
    if report["changes"]:
        for change in report["changes"]:
            st.write(f"- {change}")
    else:
        st.write("No changes were needed for the selected rules.")

    st.divider()
    st.subheader("Before vs After Data Quality")

    if st.button("Compare Quality Before and After"):
        try:
            with st.spinner("Recalculating data quality..."):
                original_response = requests.get(
                    f"{API_URL}/quality/"
                    f"{st.session_state.dataset_id}",
                    timeout=120,
                )
                original_response.raise_for_status()

                cleaned_response = requests.get(
                    f"{API_URL}/quality/{report['cleaned_id']}",
                    timeout=120,
                )
                cleaned_response.raise_for_status()

            before = original_response.json()
            after = cleaned_response.json()

            def count_missing(quality_report):
                return sum(
                    quality_report["missing_values"].values()
                )

            def count_invalid(quality_report):
                return sum(
                    quality_report["invalid_values"].values()
                )

            comparison = [
                {
                    "Quality check": "Total rows",
                    "Before": before["total_rows"],
                    "After": after["total_rows"],
                },
                {
                    "Quality check": "Missing values",
                    "Before": count_missing(before),
                    "After": count_missing(after),
                },
                {
                    "Quality check": "Exact duplicate rows",
                    "Before": before["duplicate_rows"],
                    "After": after["duplicate_rows"],
                },
                {
                    "Quality check": "Invalid numeric values",
                    "Before": count_invalid(before),
                    "After": count_invalid(after),
                },
                {
                    "Quality check": "Rows requiring review",
                    "Before": before["rows_with_issues"],
                    "After": after["rows_with_issues"],
                },
            ]

            st.dataframe(
                comparison,
                use_container_width=True,
                hide_index=True,
            )

            st.subheader("Remaining issues after cleaning")

            st.write("**Missing values**")
            if after["missing_values"]:
                st.json(after["missing_values"])
            else:
                st.success("No missing values remain.")

            st.write("**Invalid numeric values**")
            if after["invalid_values"]:
                st.json(after["invalid_values"])
            else:
                st.success("No configured invalid numeric values remain.")

            st.write("**Duplicate rows**")
            st.write(after["duplicate_rows"])

            st.write("**Inconsistent categories**")
            if after["inconsistent_categories"]:
                st.json(after["inconsistent_categories"])
            else:
                st.success("No category inconsistencies detected.")

            st.info(
                "The comparison analyzes the original and cleaned files. "
                "It does not modify either file."
            )

        except requests.RequestException as exc:
            st.error(f"Could not compare data quality: {exc}")

    st.divider()
    st.subheader("Download cleaned dataset")

    try:
        download_response = requests.get(
            f"{API_URL}/download/{report['cleaned_id']}",
            timeout=120,
        )
        download_response.raise_for_status()

        st.download_button(
            label="Download Cleaned Dataset",
            data=download_response.content,
            file_name="cleaned_dataset.csv",
            mime="text/csv",
            key="download_cleaned_dataset",
        )

    except requests.RequestException as exc:
        st.error(f"Could not prepare download: {exc}")

st.divider()
st.header("Analytics Dashboard")

st.write(
    "Generate KPIs and charts from your uploaded or cleaned dataset."
)

analytics_source = st.radio(
    "Choose dataset for analytics",
    ["Cleaned dataset", "Original uploaded dataset"],
    horizontal=True,
)

if analytics_source == "Cleaned dataset":
    analytics_id = st.session_state.get("cleaned_id")
else:
    analytics_id = st.session_state.get("dataset_id")

if not analytics_id:
    st.info(
        "Upload a dataset first. To use cleaned data, apply cleaning rules."
    )
elif st.button("Generate Analytics", type="primary"):
    try:
        with st.spinner("Generating analytics..."):
            response = requests.get(
                f"{API_URL}/analytics/{analytics_id}",
                timeout=120,
            )
        response.raise_for_status()
        analytics = response.json()

        st.session_state.analytics_report = analytics
        st.session_state.analytics_source_id = analytics_id

    except requests.RequestException as exc:
        st.error(f"Analytics generation failed: {exc}")

analytics = st.session_state.get("analytics_report")

if (
    analytics
    and analytics.get("dataset_id")
    == st.session_state.get("analytics_source_id")
):
    st.subheader("Key Performance Indicators")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total rows", analytics["total_rows"])
    col2.metric("Total orders", analytics["total_orders"])
    col3.metric("Delivered orders", analytics["delivered_orders"])
    col4.metric("Cancelled orders", analytics["cancelled_orders"])

    
    if analytics["revenue"] is not None:
        st.metric(
            "Revenue (all valid orders)",
            f"₹{analytics['revenue']:,.2f}",
        )

    col1, col2 = st.columns(2)

    if analytics.get("delivered_revenue") is not None:
        col1.metric(
            "Delivered revenue",
            f"₹{analytics['delivered_revenue']:,.2f}",
        )

    if analytics.get("cancelled_revenue") is not None:
        col2.metric(
            "Cancelled-order value",
            f"₹{analytics['cancelled_revenue']:,.2f}",
        )


    st.caption(analytics["revenue_note"])

    st.subheader("Orders by Status")
    status_data = analytics["orders_by_status"]

    if status_data:
        st.bar_chart(status_data)
    else:
        st.info("No order-status data available.")

    st.subheader("Revenue by City")
    city_data = analytics["revenue_by_city"]

    if city_data:
        st.bar_chart(city_data)
    else:
        st.info("City-based revenue is unavailable for this dataset.")

    st.subheader("Top Restaurants by Revenue")
    restaurant_data = analytics["top_restaurants_by_revenue"]

    if restaurant_data:
        st.bar_chart(restaurant_data)
    else:
        st.info("Restaurant revenue is unavailable for this dataset.")

    
    st.divider()
    st.subheader("Export Analytics for Excel / Power BI")

    import pandas as pd

    # 1. Orders by status
    status_data = analytics.get("orders_by_status", {})
    if status_data:
        status_df = pd.DataFrame(
            list(status_data.items()),
            columns=["Order Status", "Order Count"],
        )
        st.download_button(
            "Download Orders by Status (CSV)",
            data=status_df.to_csv(index=False).encode("utf-8"),
            file_name="orders_by_status.csv",
            mime="text/csv",
            key="export_orders_status",
        )

    # 2. Revenue by city
    city_data = analytics.get("revenue_by_city", {})
    if city_data:
        city_df = pd.DataFrame(
            list(city_data.items()),
            columns=["City", "Revenue"],
        )
        st.download_button(
            "Download Revenue by City (CSV)",
            data=city_df.to_csv(index=False).encode("utf-8"),
            file_name="revenue_by_city.csv",
            mime="text/csv",
            key="export_revenue_city",
        )

    # 3. Top restaurants by revenue
    restaurant_data = analytics.get(
        "top_restaurants_by_revenue", {}
    )
    if restaurant_data:
        restaurant_df = pd.DataFrame(
            list(restaurant_data.items()),
            columns=["Restaurant", "Revenue"],
        )
        st.download_button(
            "Download Top Restaurants (CSV)",
            data=restaurant_df.to_csv(index=False).encode("utf-8"),
            file_name="top_restaurants_by_revenue.csv",
            mime="text/csv",
            key="export_top_restaurants",
        )

    st.download_button(
        
        "Download Analytics Report (JSON)",
        data=__import__("json").dumps(
            analytics, indent=2, ensure_ascii=False
        ),
        file_name="food_delivery_analytics.json",
        mime="application/json",
        key="download_analytics_report",
    )

