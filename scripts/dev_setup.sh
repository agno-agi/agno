#!/bin/bash

############################################################################
#
#    Agno Development Setup
#
#    Creates .venv with agnoctl and agno installed in editable mode,
#    with everything the core dev loop needs: unit + integration tests,
#    ./scripts/format.sh and ./scripts/validate.sh.
#    Provider-SDK test dependencies live in ./scripts/test_setup.sh.
#
#    Usage: ./scripts/dev_setup.sh
#
############################################################################

set -e

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
AGNO_DIR="${REPO_ROOT}/libs/agno"
AGNOCTL_DIR="${REPO_ROOT}/libs/agnoctl"
VENV_DIR="${REPO_ROOT}/.venv"

# Colors
ORANGE='\033[38;5;208m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${ORANGE}"
cat << 'BANNER'
     █████╗  ██████╗ ███╗   ██╗ ██████╗
    ██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗
    ███████║██║  ███╗██╔██╗ ██║██║   ██║
    ██╔══██║██║   ██║██║╚██╗██║██║   ██║
    ██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝
    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝
BANNER
echo -e "${NC}"
echo -e "    ${DIM}Development Setup${NC}"
echo ""

# Preflight
if [[ -n "$VIRTUAL_ENV" ]]; then
    echo "    Deactivate your current venv first."
    exit 1
fi

if ! command -v uv &> /dev/null; then
    echo "    uv not found. Install: https://docs.astral.sh/uv/"
    exit 1
fi

# Setup
echo -e "    ${DIM}Removing old environment...${NC}"
echo -e "    ${DIM}> rm -rf ${VENV_DIR}${NC}"
rm -rf "${VENV_DIR}"

echo ""
echo -e "    ${DIM}Creating Python 3.12 venv...${NC}"
echo -e "    ${DIM}> uv venv ${VENV_DIR} --python 3.12${NC}"
uv venv "${VENV_DIR}" --python 3.12 --quiet

# One resolve for both editables: the local agnoctl satisfies agno's
# agnoctl dependency, so nothing is pulled from PyPI for it.
echo ""
echo -e "    ${DIM}Installing agnoctl[dev] and agno[dev] in editable mode...${NC}"
echo -e "    ${DIM}> uv pip install -e libs/agnoctl[dev] -e libs/agno[dev]${NC}"
VIRTUAL_ENV="${VENV_DIR}" uv pip install -e "${AGNOCTL_DIR}[dev]" -e "${AGNO_DIR}[dev]" --quiet

# Copy activation command to clipboard
ACTIVATE_CMD="source .venv/bin/activate"
if command -v pbcopy &> /dev/null; then
    echo -n "${ACTIVATE_CMD}" | pbcopy
    CLIPBOARD_MSG="(Copied to clipboard. Just paste and hit enter.)"
elif command -v xclip &> /dev/null; then
    echo -n "${ACTIVATE_CMD}" | xclip -selection clipboard
    CLIPBOARD_MSG="(Copied to clipboard. Just paste and hit enter.)"
else
    CLIPBOARD_MSG=""
fi

echo ""
echo -e "    ${BOLD}Done.${NC}"
echo ""
echo -e "    ${DIM}Activate:${NC}  ${ACTIVATE_CMD}"
echo -e "    ${DIM}Test:${NC}      pytest libs/agno/tests/unit"
echo -e "    ${DIM}Validate:${NC}  ./scripts/format.sh && ./scripts/validate.sh"
echo ""
if [[ -n "$CLIPBOARD_MSG" ]]; then
    echo -e "    ${DIM}${CLIPBOARD_MSG}${NC}"
    echo ""
fi
