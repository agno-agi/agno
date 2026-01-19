"""
Load F1 Data
============

Downloads Formula 1 data from S3 and loads it into PostgreSQL tables.

Tables created:
- constructors_championship (1958-2020)
- drivers_championship (1950-2020)
- fastest_laps (1950-2020)
- race_results (1950-2020)
- race_wins (1950-2020)

Usage:
    python scripts/load_f1_data.py

Prerequisites:
    Start PostgreSQL first:
    ./cookbook/scripts/run_pgvector.sh
"""

import sys
from io import StringIO

import pandas as pd
import requests
from agno.utils.log import logger
from sqlalchemy import create_engine, text

# ============================================================================
# Configuration
# ============================================================================
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
S3_URI = "https://agno-public.s3.amazonaws.com/f1"

# Mapping of S3 files to table names
FILES_TO_TABLES = {
    f"{S3_URI}/constructors_championship_1958_2020.csv": "constructors_championship",
    f"{S3_URI}/drivers_championship_1950_2020.csv": "drivers_championship",
    f"{S3_URI}/fastest_laps_1950_to_2020.csv": "fastest_laps",
    f"{S3_URI}/race_results_1950_to_2020.csv": "race_results",
    f"{S3_URI}/race_wins_1950_to_2020.csv": "race_wins",
}


# ============================================================================
# Connection Test
# ============================================================================
def test_connection() -> bool:
    """Test database connection before loading data."""
    try:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Cannot connect to database: {e}")
        logger.error("")
        logger.error("Make sure PostgreSQL is running:")
        logger.error("  ./cookbook/scripts/run_pgvector.sh")
        return False


# ============================================================================
# Data Loading
# ============================================================================
def load_f1_data() -> bool:
    """Load F1 data from S3 into PostgreSQL tables.

    Returns:
        bool: True if all tables loaded successfully, False otherwise.
    """
    # Test connection first
    if not test_connection():
        return False

    db_engine = create_engine(DB_URL)

    logger.info("Starting F1 data load...")
    logger.info(f"Database: {DB_URL}")

    success_count = 0
    for file_path, table_name in FILES_TO_TABLES.items():
        logger.info(f"Loading {table_name}...")

        try:
            # Download CSV from S3
            response = requests.get(file_path, verify=False, timeout=30)
            response.raise_for_status()

            # Parse CSV and load to database
            csv_data = StringIO(response.text)
            df = pd.read_csv(csv_data)

            df.to_sql(table_name, db_engine, if_exists="replace", index=False)
            logger.info(f"  ✓ Loaded {len(df):,} rows into {table_name}")
            success_count += 1

        except requests.RequestException as e:
            logger.error(f"  ✗ Failed to download {table_name}: {e}")
        except Exception as e:
            logger.error(f"  ✗ Failed to load {table_name}: {e}")

    logger.info("")
    if success_count == len(FILES_TO_TABLES):
        logger.info(
            f"F1 data load complete. {success_count}/{len(FILES_TO_TABLES)} tables loaded."
        )
        return True
    else:
        logger.error(
            f"F1 data load incomplete. {success_count}/{len(FILES_TO_TABLES)} tables loaded."
        )
        return False


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    # Disable SSL verification warnings for S3 downloads
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    success = load_f1_data()
    sys.exit(0 if success else 1)
