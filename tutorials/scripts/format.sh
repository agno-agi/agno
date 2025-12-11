#!/bin/bash

############################################################################
# Format the tutorials using ruff
# Usage: ./tutorials/scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUTORIALS_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting tutorials"

print_heading "Running: ruff format ${TUTORIALS_DIR}"
ruff format ${TUTORIALS_DIR}

print_heading "Running: ruff check --select I --fix ${TUTORIALS_DIR}"
ruff check --select I --fix ${TUTORIALS_DIR}
