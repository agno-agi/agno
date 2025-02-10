#!/bin/bash

############################################################################
# Release agno_docker to pypi
# Usage: ./libs/infra/agno_docker/scripts/release_manual.sh
# Note:
#   build & twine must be available in the venv
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNO_DOCKER_DIR="$(dirname ${CURR_DIR})"
source ${CURR_DIR}/_utils.sh

main() {
  print_heading "Releasing *agno_docker*"

  cd ${AGNO_DOCKER_DIR}
  print_heading "pwd: $(pwd)"

  print_heading "Proceed?"
  space_to_continue

  print_heading "Building agno_docker"
  python3 -m build

  print_heading "Release agno_docker to testpypi?"
  space_to_continue
  python3 -m twine upload --repository testpypi ${AGNO_DOCKER_DIR}/dist/*

  print_heading "Release agno_docker to pypi"
  space_to_continue
  python3 -m twine upload --repository pypi ${AGNO_DOCKER_DIR}/dist/*
}

main "$@"
