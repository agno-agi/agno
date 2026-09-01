#!/bin/bash

############################################################################
# Format the agnoctl library using ruff
# Usage: ./libs/agnoctl/scripts/format.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNOCTL_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

print_heading "Formatting agnoctl"

print_heading "Running: ruff format ${AGNOCTL_DIR}"
ruff format ${AGNOCTL_DIR}

print_heading "Running: ruff check --select I --fix ${AGNOCTL_DIR}"
ruff check --select I --fix ${AGNOCTL_DIR}
