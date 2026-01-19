"""
Text-to-SQL Agent - Main Entry Point
====================================

Run the complete Text-to-SQL tutorial from the command line.

Usage:
    python -m text_to_sql

    Or from the cookbook root:
    python -m cookbook.01_showcase.01_agents.text_to_sql

This will:
1. Check prerequisites
2. Load F1 data (if needed)
3. Load knowledge base (if needed)
4. Start the interactive agent
"""

import sys


def main() -> int:
    """Run the Text-to-SQL tutorial.

    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    print("=" * 60)
    print("Text-to-SQL Agent Tutorial")
    print("=" * 60)

    # Step 1: Check setup
    print("\n1. Checking setup...")
    try:
        from .scripts.check_setup import (
            check_api_keys,
            check_dependencies,
            check_postgres,
        )

        if not check_dependencies():
            print("\n   Please install missing dependencies and try again.")
            return 1

        if not check_api_keys():
            print("\n   Please set required API keys and try again.")
            return 1

        if not check_postgres():
            print("\n   Please start PostgreSQL and try again:")
            print("   ./cookbook/scripts/run_pgvector.sh")
            return 1

    except ImportError as e:
        print(f"   Failed to import check_setup: {e}")
        print("   Continuing anyway...")

    # Step 2: Load F1 data
    print("\n2. Loading F1 data...")
    try:
        from .scripts.load_f1_data import load_f1_data

        if not load_f1_data():
            print("\n   Failed to load F1 data. Check database connection.")
            return 1
    except Exception as e:
        print(f"   Error loading F1 data: {e}")
        return 1

    # Step 3: Load knowledge base
    print("\n3. Loading knowledge base...")
    try:
        from .scripts.load_knowledge import load_knowledge

        if not load_knowledge():
            print("\n   Failed to load knowledge base.")
            return 1
    except Exception as e:
        print(f"   Error loading knowledge: {e}")
        return 1

    # Step 4: Start interactive agent
    print("\n4. Starting interactive agent...")
    print("=" * 60)
    print(
        """
You can now ask questions about Formula 1 data (1950-2020).

Example questions:
  - Who won the most races in 2019?
  - List the top 5 drivers with the most championship wins
  - Compare Ferrari vs Mercedes points from 2015-2020

Type 'exit' or 'quit' to end the session.
"""
    )
    print("=" * 60)

    try:
        from .agent import sql_agent

        sql_agent.cli(stream=True)
    except KeyboardInterrupt:
        print("\n\nExiting...")
    except Exception as e:
        print(f"\nError running agent: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
