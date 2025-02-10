#!/bin/bash

############################################################################
# Format the agno_aws library using ruff
# Usage: ./libs/infra/agno_aws/scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_AWS_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting agno_aws"

print_heading "Running: ruff format ${AGNO_AWS_DIR}"
ruff format ${AGNO_AWS_DIR}

print_heading "Running: ruff check --select I --fix ${AGNO_AWS_DIR}"
ruff check --select I --fix ${AGNO_AWS_DIR}
