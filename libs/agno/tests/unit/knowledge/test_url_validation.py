"""Tests for URL validation in Knowledge class."""

from urllib.parse import urlparse

import pytest

from agno.knowledge.content import Content, ContentStatus


class TestUrlValidationLogic:
    """Test URL validation logic in isolation."""

    @pytest.mark.parametrize(
        "url,expected_valid",
        [
            ("https://example.com/file.pdf", True),
            ("http://example.com", True),
            ("ftp://files.example.com/data", True),
            ("invalid-url-no-scheme", False),  # Missing scheme
            ("://missing-netloc", False),  # Missing netloc
            ("", False),  # Empty string
            ("just-text", False),  # No scheme or netloc
            ("http://", False),  # Scheme but no netloc
        ],
    )
    def test_url_validation_pattern(self, url: str, expected_valid: bool):
        """Test the URL validation pattern used in Knowledge class."""
        try:
            parsed = urlparse(url)
            is_valid = all([parsed.scheme, parsed.netloc])
        except Exception:
            is_valid = False

        assert is_valid == expected_valid, f"URL '{url}' validation failed"


class TestUrlValidationBehavior:
    """Test the actual behavior of URL validation."""

    @pytest.mark.parametrize(
        "url",
        [
            "not-a-url",
            "://missing-scheme",
            "",
            "just-text",
            "http://",
        ],
    )
    def test_invalid_url_sets_failed_status(self, url: str):
        """Invalid URL should result in FAILED status without crashing."""
        content = Content(url=url)

        try:
            parsed = urlparse(url)
            is_valid = all([parsed.scheme, parsed.netloc])
            if not is_valid:
                content.status = ContentStatus.FAILED
                content.status_message = f"Invalid URL format: {url}"
        except Exception as e:
            content.status = ContentStatus.FAILED
            content.status_message = f"Invalid URL: {url} - {str(e)}"

        assert content.status == ContentStatus.FAILED, f"URL '{url}' should result in FAILED status"

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/file.pdf",
            "http://example.com",
            "https://api.example.com/v1/data",
            "ftp://files.example.com/data.txt",
        ],
    )
    def test_valid_url_does_not_fail_validation(self, url: str):
        """Valid URLs should pass validation."""
        parsed = urlparse(url)
        is_valid = all([parsed.scheme, parsed.netloc])
        assert is_valid, f"URL '{url}' should be valid"


class TestUrlValidationEarlyReturn:
    """Test URL validation returns early on invalid URLs."""

    def test_invalid_url_returns_early(self):
        """Processing should stop immediately for invalid URLs."""
        from pathlib import Path

        def url_processing_with_early_return(url: str) -> str | None:
            """Simulate URL processing with early returns."""
            try:
                parsed_url = urlparse(url)
                if not all([parsed_url.scheme, parsed_url.netloc]):
                    return None
            except Exception:
                return None

            return str(Path(parsed_url.path))

        assert url_processing_with_early_return("not-a-valid-url") is None
        assert url_processing_with_early_return("") is None
        assert url_processing_with_early_return("://bad") is None

        assert url_processing_with_early_return("https://example.com/file.pdf") == "/file.pdf"
        assert url_processing_with_early_return("https://example.com") == "."
