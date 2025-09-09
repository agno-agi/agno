import subprocess
from os import environ
from pathlib import Path
from sys import stderr, stdin, stdout
from typing import List

from agno.utilities.logging import logger


def find_compose_files(directory: Path) -> List[Path]:
    """Find Docker Compose files in the given directory."""
    compose_files = []
    common_names = ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]

    for name in common_names:
        compose_file = directory / name
        if compose_file.exists():
            compose_files.append(compose_file)

    return compose_files


def run_docker_compose_up(compose_file: Path, build: bool = True, detached: bool = True, pull: bool = False) -> bool:
    """Run docker compose up command."""
    cmd = ["docker", "compose", "-f", str(compose_file), "up"]

    if detached:
        cmd.append("-d")
    if build:
        cmd.append("--build")
    if pull:
        cmd.append("--pull")
        cmd.append("always")

    try:
        logger.info(f"Running: {' '.join(cmd)}")
        _ = subprocess.run(
            cmd,
            check=True,
            cwd=compose_file.parent,
            env=environ.copy(),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

        logger.info(f"Docker Compose started successfully from {compose_file}")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to start Docker Compose from {compose_file}")
        logger.error(f"Command: {' '.join(cmd)}")
        logger.error(f"Exit code: {e.returncode}")
        return False
    except FileNotFoundError:
        logger.error("Docker or docker compose command not found. Please ensure Docker is installed and in PATH.")
        return False


def run_docker_compose_down(compose_file: Path, remove_volumes: bool = False, remove_images: bool = False) -> bool:
    """Run docker compose down command."""
    cmd = ["docker", "compose", "-f", str(compose_file), "down"]

    if remove_volumes:
        cmd.append("--volumes")
    if remove_images:
        cmd.append("--rmi")
        cmd.append("all")

    try:
        logger.info(f"Running: {' '.join(cmd)}")
        _ = subprocess.run(
            cmd, check=True, cwd=compose_file.parent, env=environ.copy(), stdin=stdin, stdout=stdout, stderr=stderr
        )

        logger.info(f"Docker Compose stopped successfully from {compose_file}")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to stop Docker Compose from {compose_file}")
        logger.error(f"Command: {' '.join(cmd)}")
        logger.error(f"Exit code: {e.returncode}")
        return False
    except FileNotFoundError:
        logger.error("Docker or docker compose command not found. Please ensure Docker is installed and in PATH.")
        return False
