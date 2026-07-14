from pathlib import Path
from typing import Dict, Optional

from agno.utilities.logging import log_debug, logger


def read_pyproject_agno(pyproject_file: Path) -> Optional[Dict]:
    """
    Read the pyproject.toml file and return the "agno" tool configuration.
    """
    log_debug(f"Reading {pyproject_file}")
    try:
        # Try tomllib first (Python 3.11+), then fall back to tomli
        try:
            import tomllib

            with open(pyproject_file, "rb") as f:
                pyproject_dict = tomllib.load(f)
        except ImportError:
            import tomli  # type: ignore

            pyproject_dict = tomli.loads(pyproject_file.read_text())

        agno_conf = pyproject_dict.get("tool", {}).get("agno", None)
        if agno_conf is not None and isinstance(agno_conf, dict):
            return agno_conf
    except Exception as e:
        logger.error(f"Could not read {pyproject_file}: {e}")
    return None
