import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Skip tests that hit AWS rate limits (429) instead of failing.

    Checks both the exception message and the full test report (which includes
    captured stdout/stderr with agent error logs) for rate limit indicators.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        if call.excinfo is not None:
            error_msg = str(call.excinfo.value)
            full_repr = str(report.longrepr) if report.longrepr else ""
            sections_text = " ".join(content for _, content in report.sections)
            combined = (error_msg + full_repr + sections_text).lower()
            if any(p in combined for p in ["429", "rate limit", "rate_limit", "quota", "resource_exhausted"]):
                report.outcome = "skipped"
                report.longrepr = ("", -1, "Skipped: AWS rate limit (429)")
