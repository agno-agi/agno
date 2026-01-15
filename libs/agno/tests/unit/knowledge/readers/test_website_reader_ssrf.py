"""Tests for SSRF protection in WebsiteReader."""

import pytest

# Skip all tests if bs4 is not installed
try:
    from agno.knowledge.reader.website_reader import WebsiteReader, _validate_url_safe
except ImportError:
    pytestmark = pytest.mark.skip(reason="beautifulsoup4 not installed")
    # Define stubs so tests can be collected but will skip
    WebsiteReader = None  # type: ignore
    _validate_url_safe = None  # type: ignore


class TestSSRFProtection:
    """Test SSRF protection in WebsiteReader."""

    def test_blocks_aws_metadata_endpoint(self):
        """Test that AWS metadata endpoint is blocked."""
        with pytest.raises(ValueError, match="cloud metadata endpoint"):
            _validate_url_safe("http://169.254.169.254/latest/meta-data/")

    def test_blocks_gcp_metadata_endpoint(self):
        """Test that GCP metadata endpoint is blocked."""
        with pytest.raises(ValueError, match="cloud metadata endpoint"):
            _validate_url_safe("http://metadata.google.internal/computeMetadata/v1/")

    def test_blocks_alibaba_metadata_endpoint(self):
        """Test that Alibaba Cloud metadata endpoint is blocked."""
        with pytest.raises(ValueError, match="cloud metadata endpoint"):
            _validate_url_safe("http://100.100.100.200/latest/meta-data/")

    def test_blocks_private_ip_10_range(self):
        """Test that 10.x.x.x private IPs are blocked."""
        with pytest.raises(ValueError, match="private IP address"):
            _validate_url_safe("http://10.0.0.1/admin")

    def test_blocks_private_ip_172_range(self):
        """Test that 172.16-31.x.x private IPs are blocked."""
        with pytest.raises(ValueError, match="private IP address"):
            _validate_url_safe("http://172.16.0.1/config")

    def test_blocks_private_ip_192_168_range(self):
        """Test that 192.168.x.x private IPs are blocked."""
        with pytest.raises(ValueError, match="private IP address"):
            _validate_url_safe("http://192.168.1.1/router")

    def test_blocks_localhost_ip(self):
        """Test that 127.0.0.1 is blocked."""
        with pytest.raises(ValueError, match="loopback address"):
            _validate_url_safe("http://127.0.0.1:8080/admin")

    def test_blocks_link_local(self):
        """Test that link-local addresses are blocked."""
        with pytest.raises(ValueError, match="link-local address"):
            _validate_url_safe("http://169.254.1.1/")

    def test_blocks_invalid_scheme(self):
        """Test that non-http(s) schemes are blocked."""
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            _validate_url_safe("file:///etc/passwd")

        with pytest.raises(ValueError, match="Invalid URL scheme"):
            _validate_url_safe("ftp://internal.server/data")

    def test_allows_public_urls(self):
        """Test that public URLs are allowed."""
        # These should not raise
        _validate_url_safe("https://example.com/")
        _validate_url_safe("https://docs.agno.com/introduction")
        _validate_url_safe("http://github.com/agno-ai/agno")

    def test_allows_public_ip(self):
        """Test that public IP addresses are allowed."""
        # 8.8.8.8 is Google's public DNS
        _validate_url_safe("http://8.8.8.8/")

    def test_reader_crawl_validates_url(self):
        """Test that WebsiteReader.crawl() validates URLs."""
        reader = WebsiteReader()

        with pytest.raises(ValueError, match="not allowed"):
            reader.crawl("http://169.254.169.254/latest/meta-data/")

        with pytest.raises(ValueError, match="not allowed"):
            reader.crawl("http://192.168.1.1/admin")

    @pytest.mark.asyncio
    async def test_reader_async_crawl_validates_url(self):
        """Test that WebsiteReader.async_crawl() validates URLs."""
        reader = WebsiteReader()

        with pytest.raises(ValueError, match="not allowed"):
            await reader.async_crawl("http://169.254.169.254/latest/meta-data/")

        with pytest.raises(ValueError, match="not allowed"):
            await reader.async_crawl("http://10.0.0.1/internal")
