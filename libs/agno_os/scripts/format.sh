#!/bin/bash

############################################################################
# Format the agno_aws library using ruff
# Usage: ./libs/infra/agno_aws/scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_OS_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting agno_os"

print_heading "Running: ruff format ${AGNO_OS_DIR}"
ruff format ${AGNO_OS_DIR}

print_heading "Running: ruff check --select I --fix ${AGNO_OS_DIR}"
ruff check --select I --fix ${AGNO_OS_DIR}
