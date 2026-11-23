FROM apache/airflow:2.10.5-python3.12
USER airflow
RUN pip install --no-cache-dir apache-airflow==2.10.5 clickhouse-connect==0.8.17 psycopg2-binary==2.9.10
COPY --chown=airflow:root common /opt/airflow/common
COPY --chown=airflow:root airflow/pipeline /opt/airflow/pipeline
COPY --chown=airflow:root airflow/dags /opt/airflow/dags
ENV PYTHONPATH=/opt/airflow
