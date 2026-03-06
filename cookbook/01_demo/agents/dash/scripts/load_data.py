"""
Load F1 Data - Downloads F1 data (1950-2020) and loads into PostgreSQL.

Usage: python -m agents.dash.scripts.load_data
"""

from io import StringIO

import httpx
import pandas as pd
from db import db_url
from sqlalchemy import create_engine

S3_URI = "https://agno-public.s3.amazonaws.com/f1"

TABLES = {
    "constructors_championship": f"{S3_URI}/constructors_championship_1958_2020.csv",
    "drivers_championship": f"{S3_URI}/drivers_championship_1950_2020.csv",
    "fastest_laps": f"{S3_URI}/fastest_laps_1950_to_2020.csv",
    "race_results": f"{S3_URI}/race_results_1950_to_2020.csv",
    "race_wins": f"{S3_URI}/race_wins_1950_to_2020.csv",
}

if __name__ == "__main__":
    engine = create_engine(db_url)
    total = 0

    for table, url in TABLES.items():
        print(f"Loading {table}...", end=" ", flush=True)
        response = httpx.get(url, timeout=30.0)
        df = pd.read_csv(StringIO(response.text))
        df.to_sql(table, engine, if_exists="replace", index=False)
        print(f"{len(df):,} rows")
        total += len(df)

    print(f"\nDone! {total:,} total rows")
