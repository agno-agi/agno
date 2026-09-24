"""Fixture for the cross-process digest test.

The function lives in an importable file so two interpreters can hash the same
source; a digest embedding anything process-local (a repr's memory address) fails
the comparison.
"""


def fixture_scorer(run, expected):
    return run.content == expected
