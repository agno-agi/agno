from os import getenv
from typing import Optional


def get_from_env(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Get the value for an environment variable. Use default if not found, or raise an error if required is True."""

    value = getenv(key, default)
    if value is None and required:
        raise ValueError(f"Environment variable {key} is required but not found")
    return value
