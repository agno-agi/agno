"""Schema for metrics derived from OS-level data sources.

Unlike the regular metrics table, these rows are stored in the database backing
the OS feature that owns the source data and are not selected through ``db_id``.
"""

try:
    from sqlalchemy.types import BigInteger, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

OS_METRICS = "os_metrics"

OS_METRICS_TABLE_SCHEMA = {
    "id": {"type": String, "primary_key": True, "nullable": False},
    "users_created_count": {"type": BigInteger, "nullable": False, "default": 0},
    "date": {"type": BigInteger, "nullable": False, "index": True, "unique": True},
    "created_at": {"type": BigInteger, "nullable": False},
    "updated_at": {"type": BigInteger, "nullable": False},
}
