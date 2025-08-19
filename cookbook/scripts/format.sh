#!/bin/bash

############################################################################
# Format the cookbook using ruff
# Usage: ./libs/agno/scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COOKBOOK_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting cookbook"

print_heading "Running: ruff format ${COOKBOOK_DIR}"
ruff format ${COOKBOOK_DIR}

print_heading "Running: ruff check --select I --fix ${COOKBOOK_DIR}"
ruff check --select I --fix ${COOKBOOK_DIR}
