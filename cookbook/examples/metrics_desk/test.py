"""
Metrics Desk - CLI
==================
Runs the analyst without starting the server: ask for a number, then tell it to
delete the table and watch the database refuse.

The refusal prints a traceback from the SQL tool. That traceback is the demo
working: the write left the agent, reached SQLite, and the driver said no.
"""

from metrics_desk import analyst

# ---------------------------------------------------------------------------
# Create the run: one question, one write the connection will not allow
# ---------------------------------------------------------------------------
QUESTION = "What was total revenue by region on 2026-07-21?"
DESTRUCTIVE = "Delete the orders table."
SURVIVED = "How many rows are in the orders table now?"

# ---------------------------------------------------------------------------
# Run: measure, try to destroy, then count what is left
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n--- A question the desk answers with SQL ---\n")
    analyst.print_response(QUESTION, stream=True)

    print("\n--- The same desk, told to delete the table ---\n")
    analyst.print_response(DESTRUCTIVE, stream=True)

    print("\n--- The table is still there ---\n")
    analyst.print_response(SURVIVED, stream=True)
