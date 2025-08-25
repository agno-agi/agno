#!/bin/bash

############################################################################
# Validate all libraries
# Usage: ./scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
AGNO_INFRA_DIR="${REPO_ROOT}/libs/agno_infra"
COOKBOOK_DIR="${REPO_ROOT}/cookbook"
source ${CURR_DIR}/_utils.sh

print_heading "Validating all libraries"
source ${AGNO_DIR}/scripts/validate.sh
source ${AGNO_INFRA_DIR}/scripts/validate.sh
source ${COOKBOOK_DIR}/scripts/validate.sh
