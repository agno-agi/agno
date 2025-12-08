"""Database configuration."""

from os import getenv
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def get_db_url() -> Optional[str]:
    """Build database URL from environment variables."""
    # Prefer single DATABASE_URL if set
    if url := getenv("DATABASE_URL"):
        # Convert postgresql:// to postgresql+psycopg:// for psycopg3
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    # Build from components - all required except driver
    user = getenv("DB_USER")
    host = getenv("DB_HOST")
    port = getenv("DB_PORT")
    database = getenv("DB_DATABASE")

    # Return None if required vars are missing
    if not all([user, host, port, database]):
        return None

    driver = getenv("DB_DRIVER", "postgresql+psycopg")
    password = getenv("DB_PASS", "")

    return f"{driver}://{user}:{password}@{host}:{port}/{database}"


db_url: Optional[str] = get_db_url()
