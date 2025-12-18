from io import StringIO

import pandas as pd
import requests
from agno.utils.log import logger
from sqlalchemy import create_engine

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db_engine = create_engine(db_url)
s3_uri = "https://agno-public.s3.amazonaws.com/f1"

# List of files and their corresponding table names
files_to_tables = {
    f"{s3_uri}/constructors_championship_1958_2020.csv": "constructors_championship",
    f"{s3_uri}/drivers_championship_1950_2020.csv": "drivers_championship",
    f"{s3_uri}/fastest_laps_1950_to_2020.csv": "fastest_laps",
    f"{s3_uri}/race_results_1950_to_2020.csv": "race_results",
    f"{s3_uri}/race_wins_1950_to_2020.csv": "race_wins",
}


def load_f1_data():
    """Load F1 data into the database"""

    logger.info("Loading database.")
    # Load each CSV file into the corresponding PostgreSQL table
    for file_path, table_name in files_to_tables.items():
        logger.info(f"Loading {file_path} into {table_name} table.")
        # Download the file using requests
        response = requests.get(file_path, verify=False)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Read the CSV data from the response content
        csv_data = StringIO(response.text)
        df = pd.read_csv(csv_data)

        df.to_sql(table_name, db_engine, if_exists="replace", index=False)
        logger.info(f"{file_path} loaded into {table_name} table.")

    logger.info("Database loaded.")


if __name__ == "__main__":
    # Disable SSL verification warnings
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    load_f1_data()
