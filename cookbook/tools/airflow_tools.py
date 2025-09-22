"""
Airflow Tools - DAG Management and Workflow Automation

This example demonstrates how to use AirflowTools for managing Apache Airflow DAGs.
Shows enable_ flag patterns for selective function access.
AirflowTools is a small tool (<6 functions) so it uses enable_ flags.

Run: `pip install apache-airflow` to install the dependencies
"""

from agno.agent import Agent
from agno.tools.airflow import AirflowTools

# Example 1: All functions enabled (default behavior)
agent_full = Agent(
    tools=[AirflowTools(dags_dir="tmp/dags")],  # All functions enabled by default
    description="You are an Airflow specialist with full DAG management capabilities.",
    instructions=[
        "Help users create, read, and manage Airflow DAGs",
        "Ensure DAG files follow Airflow best practices",
        "Provide clear explanations of DAG structure and components",
    ],
    markdown=True,
)

# Example 2: Enable specific functions using enable_ flags
agent_readonly = Agent(
    tools=[
        AirflowTools(
            dags_dir="tmp/dags",
            enable_save_dag=False,  # Disable DAG creation
            enable_read_dag=True,  # Enable DAG reading
        )
    ],
    description="You are an Airflow analyst focused on reading and analyzing existing DAGs.",
    instructions=[
        "Analyze existing DAG files and provide insights",
        "Explain DAG structure and dependencies",
        "Cannot create or modify DAGs, only read them",
    ],
    markdown=True,
)

# Example 3: Enable all functions explicitly
agent_explicit = Agent(
    tools=[
        AirflowTools(
            dags_dir="tmp/dags",
            enable_save_dag=True,
            enable_read_dag=True,
        )
    ],
    description="You are an Airflow developer with explicit permissions for all DAG operations.",
    instructions=[
        "Create and manage Airflow DAGs with best practices",
        "Read existing DAGs to understand current workflows",
        "Provide comprehensive DAG analysis and recommendations",
    ],
    markdown=True,
)

# Example 4: Using the 'all=True' pattern
agent_all = Agent(
    tools=[AirflowTools(dags_dir="tmp/dags", all=True)],  # Enable all functions
    description="You are a comprehensive Airflow manager with all capabilities enabled.",
    instructions=[
        "Manage complete Airflow workflows and DAG lifecycle",
        "Create, read, and analyze DAGs as needed",
        "Provide end-to-end Airflow development support",
    ],
    markdown=True,
)

# Use the full agent for the main example
agent = agent_full


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
