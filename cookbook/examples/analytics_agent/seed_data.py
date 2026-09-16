"""Runnable companion to the analytics agent guide."""

import sqlite3

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    with sqlite3.connect("analytics.db") as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS subscriptions "
            "(account TEXT PRIMARY KEY, status TEXT, mrr_usd INTEGER)"
        )
        db.executemany(
            "INSERT OR IGNORE INTO subscriptions VALUES (?, ?, ?)",
            [
                ("Acme", "active", 1200),
                ("Beacon", "active", 800),
                ("Cedar", "cancelled", 500),
            ],
        )
