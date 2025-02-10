#!/bin/bash

############################################################################
# Run tests for all libraries
# Usage: ./scripts/test.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
AGNO_DOCKER_DIR="${REPO_ROOT}/libs/infra/agno_docker"
AGNO_AWS_DIR="${REPO_ROOT}/libs/infra/agno_aws"
source ${CURR_DIR}/_utils.sh

print_heading "Running tests for all libraries"
source ${AGNO_DIR}/scripts/test.sh
source ${AGNO_DOCKER_DIR}/scripts/test.sh
source ${AGNO_AWS_DIR}/scripts/test.sh
