FROM apache/airflow:3.3.1-python3.12

RUN pip install --no-cache-dir \
    "apache-airflow==3.3.1" \
    "duckdb>=1.2,<2.0" \
    "pandas>=2.2,<4.0" \
    "pyarrow>=19.0" \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.12.txt"
