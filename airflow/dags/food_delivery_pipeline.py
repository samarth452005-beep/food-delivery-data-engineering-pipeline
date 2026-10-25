from datetime import timedelta
from pathlib import Path
import sys

import pendulum
from airflow.sdk import dag, task, get_current_context
from airflow.exceptions import AirflowException

PROJECT_SRC = "/opt/food-delivery/src"

if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)

from incremental_pipeline import process_incoming_files


@dag(
    dag_id="food_delivery_incremental_pipeline",
    description="Orchestrate the existing food delivery incremental pipeline",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
    },
    tags=["food-delivery", "incremental", "duckdb"],
)
def food_delivery_incremental_pipeline():

    @task
    
    def process_new_files():
        context = get_current_context()

        interval_start = context["data_interval_start"].date()
        interval_end = (
            context["data_interval_end"] - timedelta(microseconds=1)
        ).date()
        print(f"Airflow data interval start: {context['data_interval_start']}")
        print(f"Airflow data interval end: {context['data_interval_end']}")
        print(f"Pipeline start_date: {interval_start}")
        print(f"Pipeline end_date: {interval_end}")
        if interval_end < interval_start:
            raise AirflowException(
                f"Invalid date interval: {interval_start} to {interval_end}"
            )

        incoming_dir = Path("/opt/food-delivery/test_incoming")
        db_path = Path(
            "/opt/food-delivery/test_data/automation.duckdb"
        )
        db_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Passing start_date={interval_start.isoformat()!r}")
        print(f"Passing end_date={interval_end.isoformat()!r}")
        results = process_incoming_files(
            db_path=str(db_path),
            incoming_dir=str(incoming_dir),
            start_date=interval_start.isoformat(),
            end_date=interval_end.isoformat(),
        )
        print(f"Pipeline results: {results}")

        failed = [
            result for result in results
            if result.get("status") == "FAILED"
        ]

        if failed:
            raise AirflowException(
                f"{len(failed)} incoming file(s) failed: {failed}"
            )

        print(f"Processed {len(results)} file result(s).")

    process_new_files()


food_delivery_incremental_pipeline()
