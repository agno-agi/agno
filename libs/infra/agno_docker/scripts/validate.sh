#!/bin/bash

############################################################################
# Validate the agno_docker library using ruff and mypy
# Usage: ./libs/infra/agno_docker/scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_DOCKER_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Validating agno_docker"

print_heading "Running: ruff check ${AGNO_DOCKER_DIR}"
ruff check ${AGNO_DOCKER_DIR}

print_heading "Running: mypy ${AGNO_DOCKER_DIR} --config-file ${AGNO_DOCKER_DIR}/pyproject.toml"
mypy ${AGNO_DOCKER_DIR} --config-file ${AGNO_DOCKER_DIR}/pyproject.toml
