#!/bin/bash

############################################################################
# Format the agno_docker library using ruff
# Usage: ./libs/infra/agno_docker/scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_DOCKER_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting agno_docker"

print_heading "Running: ruff format ${AGNO_DOCKER_DIR}"
ruff format ${AGNO_DOCKER_DIR}

print_heading "Running: ruff check --select I --fix ${AGNO_DOCKER_DIR}"
ruff check --select I --fix ${AGNO_DOCKER_DIR}
