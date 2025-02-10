#!/bin/bash

############################################################################
# Release agno to pypi
# Usage: ./libs/agno/scripts/release_manual.sh
# Note:
#   build & twine must be available in the venv
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

main() {
  print_heading "Releasing *agno*"

  cd ${AGNO_DIR}
  print_heading "pwd: $(pwd)"

  print_heading "Proceed?"
  space_to_continue

  print_heading "Building agno"
  python3 -m build

  print_heading "Release agno to testpypi?"
  space_to_continue
  python3 -m twine upload --repository testpypi ${AGNO_DIR}/dist/*

  print_heading "Release agno to pypi"
  space_to_continue
  python3 -m twine upload --repository pypi ${AGNO_DIR}/dist/*
}

main "$@"
