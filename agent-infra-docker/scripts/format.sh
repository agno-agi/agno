#!/bin/bash

############################################################################
# Format the workspace using ruff
# Usage: ./scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname $CURR_DIR)"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting workspace..."

print_heading "Running: ruff format ${REPO_ROOT}"
ruff format ${REPO_ROOT}

print_heading "Running: ruff check --select I --fix ${REPO_ROOT}"
ruff check --select I --fix ${REPO_ROOT}
