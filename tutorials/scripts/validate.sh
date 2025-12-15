#!/bin/bash

############################################################################
# Validate the tutorials using ruff
# Usage: ./tutorials/scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUTORIALS_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Validating tutorials"

print_heading "Running: ruff check ${TUTORIALS_DIR}"
ruff check ${TUTORIALS_DIR}
