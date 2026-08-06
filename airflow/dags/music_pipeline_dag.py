from datetime import timedelta

import pendulum
from airflow.operators.bash import BashOperator

from airflow import DAG

PROJECT_DIR = "/opt/music-etl-project"

default_args = {
    "owner": "kuba",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="music_pipeline",
    default_args=default_args,
    description="Täglicher Extract → Load → Transform der Last.fm Scrobbles",
    schedule="0 8 * * *",
    start_date=pendulum.datetime(2026, 7, 28, tz="UTC"),
    catchup=False,
) as dag:

    extract = BashOperator(
        task_id="extract",
        bash_command=f"pip install requests python-dotenv --quiet && cd {PROJECT_DIR} && python extract.py",
    )

    load = BashOperator(
        task_id="load",
        bash_command=f"pip install duckdb --quiet && cd {PROJECT_DIR} && python load_to_duckdb.py",
    )

    transform = BashOperator(
        task_id="transform",
        bash_command=f"pip install dbt-core dbt-duckdb --quiet && cd {PROJECT_DIR}/music_transform && dbt run --profiles-dir {PROJECT_DIR}/music_transform",
        env={"DUCKDB_PATH": "/opt/music-etl-project/music_pipeline.duckdb"},
    )

    extract >> load >> transform