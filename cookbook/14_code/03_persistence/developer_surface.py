"""
CodeMode - The developer surface
================================

Besides the two model-facing tools, CodeMode has a programmatic surface for
the developer: `run` a cell, list `variables`, pull a `value` back into the
host process by dill round-trip, and `shutdown` a session's kernel. Every
method has an `a`-prefixed async twin.

This runs without a model, so it is the cheapest way to see the kernel work.
"""

from agno.tools.code import CodeMode

SESSION_ID = "developer-surface"

# ---------------------------------------------------------------------------
# Run cells directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    code = CodeMode()
    try:
        first = code.run(
            SESSION_ID,
            "import statistics\nreadings = [3, 1, 4, 1, 5, 9, 2, 6]\nlen(readings)",
        )
        print("cell 1 status:", first.status, "| result:", first.result)

        second = code.run(
            SESSION_ID,
            "mean = statistics.mean(readings)\nprint(f'mean is {mean}')\nmean",
        )
        print("cell 2 stdout:", second.stdout.strip(), "| result:", second.result)

        # State persisted across the two cells, and the host can read it back.
        print("variables:", code.variables(SESSION_ID))
        print("readings pulled into this process:", code.value(SESSION_ID, "readings"))

        # A traceback is a result, not a crash: the kernel survives it.
        failed = code.run(SESSION_ID, "1 / 0")
        print(
            "cell 3 status:",
            failed.status,
            "| last traceback line:",
            failed.traceback.splitlines()[-1],
        )
        print("kernel still alive:", code.run(SESSION_ID, "mean").result)
    finally:
        code.shutdown()
