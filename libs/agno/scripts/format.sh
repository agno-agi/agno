#!/bin/bash

############################################################################
# Format the agno library using ruff
# Usage: ./libs/agno/scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting agno"

print_heading "Running: ruff format ${AGNO_DIR}"
ruff format ${AGNO_DIR}

print_heading "Running: ruff check --select I --fix ${AGNO_DIR}"
ruff check --select I --fix ${AGNO_DIR}
