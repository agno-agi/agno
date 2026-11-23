import pytest

# Failure text that indicates Google couldn't serve the request, not that our
# code is wrong: 429 quota exhaustion and 503 UNAVAILABLE capacity brownouts
# ("This model is currently experiencing high demand"). The 503 markers are
# kept specific (paired with the code or the demand message) so a genuine
# failure that merely contains the word "unavailable" still fails.
_AVAILABILITY_MARKERS = [
    "429",
    "rate limit",
    "rate_limit",
    "quota",
    "resource_exhausted",
    "503 unavailable",
    "'code': 503",
    '"code": 503',
    "high demand",
]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Skip tests that fail on Google availability (429 quota, 503 brownout).

    Checks both the exception message and the full test report (which includes
    captured stdout/stderr with agent error logs) for availability indicators.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        if call.excinfo is not None:
            error_msg = str(call.excinfo.value)
            full_repr = str(report.longrepr) if report.longrepr else ""
            sections_text = " ".join(content for _, content in report.sections)
            combined = (error_msg + full_repr + sections_text).lower()
            matched = next((p for p in _AVAILABILITY_MARKERS if p in combined), None)
            if matched is not None:
                report.outcome = "skipped"
                report.longrepr = ("", -1, f"Skipped: Google API availability ({matched})")
