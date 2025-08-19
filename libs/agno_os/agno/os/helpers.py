from pathlib import Path
from typing import Optional

from agno.utils.logging import logger


def get_os_infra_dir_from_env() -> Optional[Path]:
    from os import getenv

    from agno.constants import AGNO_OS_INFRA_DIR

    logger.debug(f"Reading {AGNO_OS_INFRA_DIR} from environment variables")
    os_infra_dir = getenv(AGNO_OS_INFRA_DIR, None)
    if os_infra_dir is not None:
        return Path(os_infra_dir)
    return None


def get_os_infra_dir_path(os_root_path: Path) -> Path:
    """
    Get the infra directory path from the given project root path.
    Agno infra dir can be found at:
        1. subdirectory: infra
        2. In a folder defined by the pyproject.toml file
    """
    from agno.utils.pyproject import read_pyproject_agno

    logger.debug(f"Searching for a os directory in {os_root_path}")

    # Case 1: Look for a subdirectory with name: infra
    os_infra_dir = os_root_path.joinpath("infra")
    logger.debug(f"Searching {os_infra_dir}")
    if os_infra_dir.exists() and os_infra_dir.is_dir():
        return os_infra_dir

    # Case 2: Look for a folder defined by the pyproject.toml file
    pyproject_toml_path = os_root_path.joinpath("pyproject.toml")
    if pyproject_toml_path.exists() and pyproject_toml_path.is_file():
        agno_conf = read_pyproject_agno(pyproject_toml_path)
        if agno_conf is not None:
            agno_conf_infra_dir_str = agno_conf.get("infra-path", None)
            if agno_conf_infra_dir_str is not None:
                agno_conf_infra_dir_path = os_root_path.joinpath(agno_conf_infra_dir_str)
            else:
                logger.error("Infra directory not specified in pyproject.toml")
                exit(0)
            logger.debug(f"Searching {agno_conf_infra_dir_path}")
            if agno_conf_infra_dir_path.exists() and agno_conf_infra_dir_path.is_dir():
                return agno_conf_infra_dir_path

    logger.error(f"Could not find a infra directory at: {os_root_path}")
    exit(0)
