import pytest


@pytest.fixture(autouse=True)
def skip_on_rate_limit():
    """Skip tests that hit SambaNova rate limits (429) instead of failing."""
    try:
        yield
    except Exception as e:
        if "429" in str(e) or "rate limit" in str(e).lower():
            pytest.skip("SambaNova rate limit (429)")
        raise
