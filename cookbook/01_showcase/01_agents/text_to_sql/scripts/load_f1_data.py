"""
Load F1 Data
============

Downloads Formula 1 data (1950-2020) from S3 and loads it into PostgreSQL.

Usage:
    python scripts/load_f1_data.py
"""

import sys
from io import StringIO

import pandas as pd
import requests
import urllib3
from sqlalchemy import create_engine

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
S3_URI = "https://agno-public.s3.amazonaws.com/f1"

FILES_TO_TABLES = {
    f"{S3_URI}/constructors_championship_1958_2020.csv": "constructors_championship",
    f"{S3_URI}/drivers_championship_1950_2020.csv": "drivers_championship",
    f"{S3_URI}/fastest_laps_1950_to_2020.csv": "fastest_laps",
    f"{S3_URI}/race_results_1950_to_2020.csv": "race_results",
    f"{S3_URI}/race_wins_1950_to_2020.csv": "race_wins",
}


def load_f1_data() -> bool:
    """Load F1 data from S3 into PostgreSQL."""
    engine = create_engine(DB_URL)

    for file_path, table_name in FILES_TO_TABLES.items():
        try:
            response = requests.get(file_path, verify=False, timeout=30)
            response.raise_for_status()
            df = pd.read_csv(StringIO(response.text))
            df.to_sql(table_name, engine, if_exists="replace", index=False)
            print(f"Loaded {table_name} successfully")
        except Exception as e:
            print(f"Failed to load {table_name}: {e}")
            return False
    print("All data loaded successfully")
    return True


if __name__ == "__main__":
    success = load_f1_data()
    sys.exit(0 if success else 1)
