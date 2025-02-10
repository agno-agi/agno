from agno.agent import Agent
from agno.tools.airflow import AirflowTools

agent = Agent(
    tools=[AirflowTools(dags_dir="tmp/dags", save_dag=True, read_dag=True)],
    show_tool_calls=True,
    markdown=True,
)


dag_content = """
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# Using 'schedule' instead of deprecated 'schedule_interval'
with DAG(
    'example_dag',
    default_args=default_args,
    description='A simple example DAG',
    schedule='@daily',  # Changed from schedule_interval
    catchup=False
) as dag:

    def print_hello():
        print("Hello from Airflow!")
        return "Hello task completed"

    task = PythonOperator(
        task_id='hello_task',
        python_callable=print_hello,
        dag=dag,
    )
"""

agent.run(f"Save this DAG file as 'example_dag.py': {dag_content}")


agent.print_response("Read the contents of 'example_dag.py'")
