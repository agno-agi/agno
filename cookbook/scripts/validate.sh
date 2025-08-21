#!/bin/bash

############################################################################
# Validate the agno library using ruff and mypy
# Usage: ./libs/agno/scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COOKBOOK_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Validating cookbook"

print_heading "Running: ruff check ${COOKBOOK_DIR}"
ruff check ${COOKBOOK_DIR}

print_heading "Running: mypy ${COOKBOOK_DIR}"
mypy ${COOKBOOK_DIR}
