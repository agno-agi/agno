#!/bin/bash

############################################################################
# Validate workspace using ruff and mypy
#   1. Lint using ruff
#   2. Type check using mypy
# Usage: ./scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname $CURR_DIR)"
source ${CURR_DIR}/_utils.sh

print_heading "Validating workspace..."

print_heading "Running: ruff check ${REPO_ROOT}"
ruff check ${REPO_ROOT}

print_heading "Running: mypy ${REPO_ROOT} --config-file ${REPO_ROOT}/pyproject.toml"
mypy ${REPO_ROOT} --config-file ${REPO_ROOT}/pyproject.toml
