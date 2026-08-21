#!/bin/bash

############################################################################
# Performance Testing Setup
# - Create a virtual environment and install libraries in editable mode.
# - Please install uv before running this script.
# - Please deactivate the existing virtual environment before running.
# Usage: ./scripts/perf_setup.sh
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
source "${CURR_DIR}/_utils.sh"

VENV_DIR="${REPO_ROOT}/.venvs/perfenv"
PYTHON_VERSION=$(python3 --version)

print_heading "Performance Testing setup..."

print_heading "Removing virtual env"
print_info "rm -rf ${VENV_DIR}"
rm -rf ${VENV_DIR}

print_heading "Creating virtual env"
print_info "uv venv --python 3.12 ${VENV_DIR}"
uv venv --python 3.12 ${VENV_DIR}

print_heading "Installing libraries"
# agno installs editable from this checkout: the benchmarks measure the local
# tree, not the last release. The os extra is required because agno.workflow
# imports fastapi. The other frameworks are the comparison set for
# cookbook/performance/comparison and cookbook/09_evals/performance/comparison.
VIRTUAL_ENV=${VENV_DIR} uv pip install -e "${AGNO_DIR}[os]" langgraph langchain_openai openai-agents crewai pydantic_ai smolagents autogen-agentchat "autogen-ext[openai]"

print_heading "uv pip list"
VIRTUAL_ENV=${VENV_DIR} uv pip list

print_heading "Performance Testing setup complete"
print_heading "Activate venv using: source ${VENV_DIR}/bin/activate"
