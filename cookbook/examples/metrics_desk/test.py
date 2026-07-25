"""
Metrics Desk - CLI
==================
Runs the analyst without starting the server: ask for a number, then tell it to
delete the table and watch the database refuse.
"""

from metrics_desk import analyst

# ---------------------------------------------------------------------------
# Create the run: one question, one write the connection will not allow
# ---------------------------------------------------------------------------
QUESTION = "What was total revenue by region on 2026-07-21?"
DESTRUCTIVE = "Delete the orders table."

# ---------------------------------------------------------------------------
# Run: measure, then try to destroy
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n--- A question the desk answers with SQL ---\n")
    analyst.print_response(QUESTION, stream=True)

    print("\n--- The same desk, told to delete the table ---\n")
    analyst.print_response(DESTRUCTIVE, stream=True)
