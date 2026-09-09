#!/bin/bash

############################################################################
#
#    Agno Format
#
#    ruff format + import sort for agno, agnoctl, agno_infra and cookbook.
#
#    Usage: ./scripts/format.sh
#
############################################################################

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"

# Colors
ORANGE='\033[38;5;208m'
GREEN='\033[32m'
RED='\033[31m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

# Fall back to the dev venv tools when not already on PATH
if ! command -v ruff &> /dev/null && [[ -x "${REPO_ROOT}/.venv/bin/ruff" ]]; then
    export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
fi
if ! command -v ruff &> /dev/null; then
    echo "    ruff not found. Run ./scripts/dev_setup.sh first."
    exit 1
fi

echo ""
echo -e "    ${BOLD}Agno Format${NC}"

FAILURES=()
CURRENT_TARGET=""
START=${SECONDS}

target() {
    CURRENT_TARGET="$1"
    echo ""
    echo -e "    ${ORANGE}${CURRENT_TARGET}${NC}"
}

run_step() {
    local label="$1"
    shift
    local output
    if output="$("$@" 2>&1)"; then
        local summary
        summary="$(printf '%s' "${output}" | tail -n 1)"
        echo -e "    ${GREEN}✓${NC} ${label}${summary:+ ${DIM}— ${summary}${NC}}"
    else
        echo -e "    ${RED}✗ ${label}${NC}"
        printf '%s\n' "${output}" | sed 's/^/      /'
        FAILURES+=("${CURRENT_TARGET}: ${label}")
    fi
}

target "agno"
run_step "ruff format" ruff format "${REPO_ROOT}/libs/agno"
run_step "import sort" ruff check --select I --fix "${REPO_ROOT}/libs/agno"

target "agnoctl"
run_step "ruff format" ruff format "${REPO_ROOT}/libs/agnoctl"
run_step "import sort" ruff check --select I --fix "${REPO_ROOT}/libs/agnoctl"

target "agno_infra"
run_step "ruff format" ruff format "${REPO_ROOT}/libs/agno_infra"
run_step "import sort" ruff check --select I --fix "${REPO_ROOT}/libs/agno_infra"

target "cookbook"
run_step "ruff format" ruff format "${REPO_ROOT}/cookbook"
run_step "import sort" ruff check --select I --fix "${REPO_ROOT}/cookbook"

ELAPSED=$((SECONDS - START))
echo ""
if [[ ${#FAILURES[@]} -eq 0 ]]; then
    echo -e "    ${BOLD}Formatted in ${ELAPSED}s.${NC}"
    echo ""
else
    echo -e "    ${BOLD}${RED}Failed:${NC} ${FAILURES[*]}"
    echo ""
    exit 1
fi
