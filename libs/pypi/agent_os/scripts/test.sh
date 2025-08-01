#!/bin/bash

############################################################################
# Run tests for the agno library
# Usage: ./libs/infra/agno_aws/scripts/test.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_OS_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Running tests for agno"

print_heading "Running: pytest ${AGNO_OS_DIR}"
pytest ${AGNO_OS_DIR}/tests
