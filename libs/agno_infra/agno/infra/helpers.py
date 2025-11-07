from pathlib import Path
from typing import Optional

from agno.utilities.logging import log_debug


def get_infra_dir_from_env() -> Optional[Path]:
    from os import getenv

    from agno.constants import AGNO_INFRA_DIR

    log_debug(f"Reading {AGNO_INFRA_DIR} from environment variables")
    infra_dir = getenv(AGNO_INFRA_DIR, None)
    if infra_dir is not None:
        return Path(infra_dir)
    return None


def is_docker_only_project(infra_root_path: Path) -> bool:
    """
    Check if the project is a docker only project.
    """

    infrastructure_indicators = [
        "compose.yaml",
        "docker-compose.yaml",
        "docker-compose.yml",
        "Dockerfile",
        "compose.yml",
    ]

    for indicator in infrastructure_indicators:
        if infra_root_path.joinpath(indicator).exists():
            log_debug(f"Found infrastructure file '{indicator}' - using root directory as infra path")
            return True
    return False


def get_infra_dir_path(infra_root_path: Path) -> Optional[Path]:
    """
    Get the infra directory path from the given project root path.
    Agno infra dir can be found at:
        1. subdirectory: infra
        2. In a folder defined by the pyproject.toml file
        3. Fallback to root directory if it contains infrastructure files
        4. Returns None if not found (instead of exiting)
    """
    from agno.utilities.pyproject import read_pyproject_agno

    log_debug(f"Searching for a infra directory in {infra_root_path}")

    # Case 1: Look for a subdirectory with name: infra
    infra_dir = infra_root_path.joinpath("infra")
    log_debug(f"Searching {infra_dir}")
    if infra_dir.exists() and infra_dir.is_dir():
        return infra_dir

    # Case 2: Look for a folder defined by the pyproject.toml file
    pyproject_toml_path = infra_root_path.joinpath("pyproject.toml")
    if pyproject_toml_path.exists() and pyproject_toml_path.is_file():
        agno_conf = read_pyproject_agno(pyproject_toml_path)
        if agno_conf is not None:
            agno_conf_infra_dir_str = agno_conf.get("infra-path", None)
            if agno_conf_infra_dir_str is not None:
                agno_conf_infra_dir_path = infra_root_path.joinpath(agno_conf_infra_dir_str)
                log_debug(f"Searching {agno_conf_infra_dir_path}")
                if agno_conf_infra_dir_path.exists() and agno_conf_infra_dir_path.is_dir():
                    return agno_conf_infra_dir_path

    log_debug(f"Could not find a infra directory at: {infra_root_path}")
    return None
