"""
Generate Progress Report
========================

Generate progress reports from Linear data.
Demonstrates report generation and analysis.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/linear_agent/examples/progress_report.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import linear_agent  # noqa: E402

# ============================================================================
# Progress Report Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Generate Progress Report")
    print("=" * 60)
    print()
    print("This example generates a progress report from Linear data.")
    print()
    print("-" * 60)
    print()

    linear_agent.print_response(
        """Generate a progress report that includes:

1. Overview of all teams
2. High priority issues that need attention
3. Any blockers or risks

Format it as an executive summary suitable for a standup meeting.""",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Workload analysis
    print("Workload Analysis...")
    print("-" * 40)
    linear_agent.print_response(
        "Analyze the current workload. What are the most pressing items?",
        stream=True,
    )

    # Uncomment for interactive mode
    # linear_agent.cli_app(stream=True)
