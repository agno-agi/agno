from pathlib import Path
from typing import Dict, Optional

from agno.utils.log import logger


def read_pyproject_agno(pyproject_file: Path) -> Optional[Dict]:
    logger.debug(f"Reading {pyproject_file}")
    try:
        import tomli

        pyproject_dict = tomli.loads(pyproject_file.read_text())
        agno_conf = pyproject_dict.get("tool", {}).get("agno", None)
        if agno_conf is not None and isinstance(agno_conf, dict):
            return agno_conf
    except Exception as e:
        logger.error(f"Could not read {pyproject_file}: {e}")
    return None
