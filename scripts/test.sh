#!/bin/bash

############################################################################
# Run tests for all libraries
# Usage: ./scripts/test.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
AGNO_INFRA_DIR="${REPO_ROOT}/libs/agno_infra"
source ${CURR_DIR}/_utils.sh

print_heading "Running tests with coverage for all libraries"

# Run tests with coverage for each library
source ${AGNO_INFRA_DIR}/scripts/test.sh
source ${AGNO_DIR}/scripts/test.sh

# Combine coverage reports (optional)
coverage combine
coverage report
coverage html -d coverage_report
