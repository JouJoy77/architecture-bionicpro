import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

from pipeline.etl import run_day


def prepare_interval(data_interval_start, data_interval_end, **context):
    return run_day(data_interval_start, data_interval_end)


with DAG(
    dag_id="bionicpro_daily_reports",
    description="CRM + телеметрия: готовая суточная витрина отчетов",
    start_date=pendulum.parse(os.environ.get("ETL_START_DATE", "2026-11-12"), tz="UTC"),
    schedule="0 0 * * *",
    catchup=True,
    max_active_runs=1,
    is_paused_upon_creation=False,
    default_args={
        "owner": "bionicpro",
        "retries": 2,
        "retry_delay": timedelta(minutes=1),
    },
    dagrun_timeout=timedelta(hours=1),
    tags=["reports", "RU"],
) as dag:
    PythonOperator(
        task_id="extract_transform_publish",
        python_callable=prepare_interval,
        execution_timeout=timedelta(minutes=45),
        do_xcom_push=False,
    )
