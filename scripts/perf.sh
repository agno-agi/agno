#!/bin/bash

############################################################################
#
#    Agno Performance Benchmarks
#
#    Runs the full suite: the agno benchmarks, the cross-framework
#    comparison, and the HTML report. Creates the environment first if
#    it does not exist.
#
#    Usage: ./scripts/perf.sh              # everything
#           ./scripts/perf.sh --quick      # 30-second smoke
#           ./scripts/perf.sh --agno-only  # skip the cross-framework suite
#
############################################################################

set -e

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
VENV_DIR="${REPO_ROOT}/.venvs/perfenv"
RUNNER="${REPO_ROOT}/cookbook/performance/run_all.py"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    "${CURR_DIR}/perf_setup.sh"
fi

MODE="--all"
QUICK=""
for arg in "$@"; do
    case "$arg" in
        --agno-only) MODE="" ;;
        --quick) QUICK="--quick" ;;
        *)
            echo "Unknown option: $arg"
            echo "Usage: ./scripts/perf.sh [--quick] [--agno-only]"
            exit 1
            ;;
    esac
done

exec "${VENV_DIR}/bin/python" "${RUNNER}" ${MODE} ${QUICK}
