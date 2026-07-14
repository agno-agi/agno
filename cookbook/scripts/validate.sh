#!/bin/bash

############################################################################
# Validate the agno library using ruff and mypy
# Usage: ./libs/agno/scripts/validate.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COOKBOOK_DIR="$(dirname ${CURR_DIR})"
AGNO_DIR="${COOKBOOK_DIR}/../libs/agno"
source ${CURR_DIR}/_utils.sh

print_heading "Validating cookbook"

print_heading "Running: ruff check ${COOKBOOK_DIR}"
ruff check ${COOKBOOK_DIR}

print_heading "Running: python3 ${CURR_DIR}/check_cookbook_pattern.py --base-dir ${COOKBOOK_DIR}/00_quickstart"
python3 ${CURR_DIR}/check_cookbook_pattern.py --base-dir ${COOKBOOK_DIR}/00_quickstart

# Not validating cookbook for now
# print_heading "Running: mypy ${COOKBOOK_DIR} --config-file ${AGNO_DIR}/pyproject.toml"
# mypy ${COOKBOOK_DIR} --config-file ${AGNO_DIR}/pyproject.toml
