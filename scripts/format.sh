#!/bin/bash

############################################################################
# Format all libraries
# Usage: ./scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
AGNO_DOCKER_DIR="${REPO_ROOT}/libs/infra/agno_docker"
AGNO_AWS_DIR="${REPO_ROOT}/libs/infra/agno_aws"
COOKBOOK_DIR="${REPO_ROOT}/cookbook"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting all libraries"
source ${AGNO_DIR}/scripts/format.sh
source ${AGNO_DOCKER_DIR}/scripts/format.sh
source ${AGNO_AWS_DIR}/scripts/format.sh

# Format all cookbook examples
source ${COOKBOOK_DIR}/scripts/format.sh
