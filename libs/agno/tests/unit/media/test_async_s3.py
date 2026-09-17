"""Tests for AsyncS3MediaStorage with a mocked aioboto3 client.

AsyncS3MediaStorage is a genuine aioboto3 reimplementation (not a sync delegator), so it
gets its own coverage. Each operation opens ``session.client("s3")`` as an async context
manager, so the mock session returns an async-CM wrapping a client with AsyncMock methods.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest


def _storage_with_client(client, **kwargs):
    """Build an AsyncS3MediaStorage whose session yields ``client`` from client("s3")."""
    from agno.media.storage.s3 import AsyncS3MediaStorage

    storage = AsyncS3MediaStorage(bucket="test-bucket", **kwargs)

    @asynccontextmanager
    async def _client_cm(*args, **kw):
        yield client

    session = MagicMock()
    session.client = _client_cm
    storage._get_session = lambda: session  # type: ignore[method-assign]
    return storage


class TestAsyncS3MediaStorage:
    @pytest.mark.asyncio
    async def test_upload(self):
        client = MagicMock()
        client.put_object = AsyncMock()
        storage = _storage_with_client(client, region="us-east-1")

        key = await storage.upload("media-1", b"content", mime_type="image/png", filename="photo.png")

        client.put_object.assert_awaited_once()
        call_kwargs = client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Body"] == b"content"
        assert call_kwargs["ContentType"] == "image/png"
        assert key.endswith(".png")

    @pytest.mark.asyncio
    async def test_upload_surfaces_an_acl_config_error(self):
        from agno.media.storage.s3 import AsyncS3MediaStorage

        client_error = pytest.importorskip("botocore.exceptions").ClientError

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def put_object(self, **kwargs):
                raise client_error({"Error": {"Code": "AccessControlListNotSupported"}}, "PutObject")

        storage = AsyncS3MediaStorage(bucket="my-bucket", acl="public-read")
        storage._get_session = lambda: MagicMock(client=MagicMock(return_value=_FakeClient()))  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="Drop the acl argument"):
            await storage.upload("media-1", b"content", mime_type="image/png")

    @pytest.mark.asyncio
    async def test_download(self):
        body = MagicMock()
        body.read = AsyncMock(return_value=b"file-content")
        client = MagicMock()
        client.get_object = AsyncMock(return_value={"Body": body})
        storage = _storage_with_client(client)

        result = await storage.download("some/key.png")

        assert result == b"file-content"
        client.get_object.assert_awaited_once_with(Bucket="test-bucket", Key="some/key.png")

    @pytest.mark.asyncio
    async def test_download_missing_object_raises_filenotfound(self):
        """S3 NoSuchKey must surface as FileNotFoundError so the router returns 404, not 500."""
        client_error = pytest.importorskip("botocore.exceptions").ClientError
        client = MagicMock()
        client.get_object = AsyncMock(side_effect=client_error({"Error": {"Code": "NoSuchKey"}}, "GetObject"))
        storage = _storage_with_client(client)

        with pytest.raises(FileNotFoundError):
            await storage.download("missing/key.png")

    @pytest.mark.asyncio
    async def test_download_other_client_error_propagates(self):
        """A non-missing error (e.g. AccessDenied) must NOT be masked as FileNotFoundError."""
        client_error = pytest.importorskip("botocore.exceptions").ClientError
        client = MagicMock()
        client.get_object = AsyncMock(side_effect=client_error({"Error": {"Code": "AccessDenied"}}, "GetObject"))
        storage = _storage_with_client(client)

        with pytest.raises(client_error):
            await storage.download("some/key.png")

    @pytest.mark.asyncio
    async def test_get_url_presigned(self):
        client = MagicMock()
        client.generate_presigned_url = AsyncMock(return_value="https://presigned.example.com")
        storage = _storage_with_client(client, presigned_url_expiry=7200)

        url = await storage.get_url("some/key.png")

        assert url == "https://presigned.example.com"
        # The configured expiry is honored (no-arg call resolves to presigned_url_expiry).
        assert client.generate_presigned_url.call_args[1]["ExpiresIn"] == 7200

    @pytest.mark.asyncio
    async def test_get_url_explicit_expiry_overrides_the_configured_one(self):
        client = MagicMock()
        client.generate_presigned_url = AsyncMock(return_value="https://presigned.example.com")
        storage = _storage_with_client(client, presigned_url_expiry=7200)

        await storage.get_url("some/key.png", expires_in=60)
        assert client.generate_presigned_url.call_args[1]["ExpiresIn"] == 60

        await storage.get_url("some/key.png", expires_in=None)
        assert client.generate_presigned_url.call_args[1]["ExpiresIn"] == 7200

    @pytest.mark.asyncio
    async def test_get_url_expires_in_zero_is_taken_literally(self):
        """Only None means "use the configured expiry".

        An explicit 0 asks for an already-expired URL and must be passed through — a
        falsy-instead-of-None guard here would silently hand back a live one-hour URL.
        """
        client = MagicMock()
        client.generate_presigned_url = AsyncMock(return_value="https://presigned.example.com")
        storage = _storage_with_client(client, presigned_url_expiry=3600)

        await storage.get_url("some/key.png", expires_in=0)
        assert client.generate_presigned_url.call_args[1]["ExpiresIn"] == 0

    @pytest.mark.asyncio
    async def test_get_url_public(self):
        storage = _storage_with_client(MagicMock(), region="us-west-2", acl="public-read")
        url = await storage.get_url("some/key.png")

        assert "test-bucket" in url
        assert "us-west-2" in url
        assert "some/key.png" in url

    @pytest.mark.asyncio
    async def test_get_url_public_endpoint_url(self):
        storage = _storage_with_client(MagicMock(), endpoint_url="http://localhost:9000", acl="public-read")
        url = await storage.get_url("some/key.png")
        assert url.startswith("http://localhost:9000/test-bucket/")

    @pytest.mark.asyncio
    async def test_exists_true(self):
        client = MagicMock()
        client.head_object = AsyncMock()
        storage = _storage_with_client(client)

        assert await storage.exists("some/key.png") is True
        client.head_object.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exists_false(self):
        client = MagicMock()
        client.head_object = AsyncMock(side_effect=Exception("Not found"))
        storage = _storage_with_client(client)

        assert await storage.exists("nonexistent/key.png") is False

    @pytest.mark.asyncio
    async def test_delete(self):
        client = MagicMock()
        client.delete_object = AsyncMock()
        storage = _storage_with_client(client)

        assert await storage.delete("some/key.png") is True
        client.delete_object.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_failure_returns_false(self):
        client = MagicMock()
        client.delete_object = AsyncMock(side_effect=Exception("boom"))
        storage = _storage_with_client(client)

        assert await storage.delete("some/key.png") is False

    @pytest.mark.asyncio
    async def test_delete_many_batches_and_subtracts_errors(self):
        from agno.media.storage.s3 import AsyncS3MediaStorage

        class _FakeClient:
            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def delete_objects(self, **kwargs):
                self.calls.append(kwargs)
                return {"Errors": [{"Key": "b"}]}

        fake = _FakeClient()
        storage = AsyncS3MediaStorage(bucket="test-bucket")
        storage._get_session = lambda: MagicMock(client=MagicMock(return_value=fake))  # type: ignore[method-assign]

        assert await storage.delete_many(["a", "b", "c"]) == 2
        assert fake.calls[0]["Delete"]["Objects"] == [{"Key": "a"}, {"Key": "b"}, {"Key": "c"}]

    def test_backend_name(self):
        from agno.media.storage.s3 import AsyncS3MediaStorage

        assert AsyncS3MediaStorage(bucket="test").backend_name == "s3"
