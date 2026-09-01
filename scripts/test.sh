#!/bin/bash

############################################################################
# Run tests for all libraries
# Usage: ./scripts/test.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
source ${CURR_DIR}/_utils.sh

print_heading "Running tests with coverage for all libraries"

# agno-infra is not part of the dev venv; it tests in its own CI job.
source ${AGNO_DIR}/scripts/test.sh

# Combine coverage reports (optional)
coverage combine
coverage report
coverage html -d coverage_report
