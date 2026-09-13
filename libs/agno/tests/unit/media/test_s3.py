"""Tests for S3MediaStorage with mocked boto3."""

from unittest.mock import MagicMock

import pytest


class TestS3MediaStorage:
    def test_upload(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        storage = S3MediaStorage(bucket="test-bucket", region="us-east-1")
        storage._client = mock_client

        key = storage.upload("media-1", b"content", mime_type="image/png", filename="photo.png")

        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Body"] == b"content"
        assert call_kwargs["ContentType"] == "image/png"
        assert key.endswith(".png")

    def test_download(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"file-content"
        mock_client.get_object.return_value = {"Body": mock_body}

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        result = storage.download("some/key.png")

        assert result == b"file-content"
        mock_client.get_object.assert_called_once_with(Bucket="test-bucket", Key="some/key.png")

    def test_download_missing_object_raises_filenotfound(self):
        """S3 NoSuchKey must surface as FileNotFoundError so the router returns 404, not 500."""
        from agno.media.storage.s3 import S3MediaStorage

        client_error = pytest.importorskip("botocore.exceptions").ClientError
        mock_client = MagicMock()
        mock_client.get_object.side_effect = client_error({"Error": {"Code": "NoSuchKey"}}, "GetObject")

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        with pytest.raises(FileNotFoundError):
            storage.download("missing/key.png")

    def test_download_other_client_error_propagates(self):
        """A non-missing error (e.g. AccessDenied) must NOT be masked as FileNotFoundError."""
        from agno.media.storage.s3 import S3MediaStorage

        client_error = pytest.importorskip("botocore.exceptions").ClientError
        mock_client = MagicMock()
        mock_client.get_object.side_effect = client_error({"Error": {"Code": "AccessDenied"}}, "GetObject")

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        with pytest.raises(client_error):
            storage.download("some/key.png")

    def test_get_url_presigned(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://presigned.example.com"

        storage = S3MediaStorage(bucket="test-bucket", presigned_url_expiry=7200)
        storage._client = mock_client
        url = storage.get_url("some/key.png")

        assert url == "https://presigned.example.com"
        mock_client.generate_presigned_url.assert_called_once()
        # No-arg call resolves to the configured expiry.
        assert mock_client.generate_presigned_url.call_args[1]["ExpiresIn"] == 7200

    def test_get_url_explicit_expiry_overrides_the_configured_one(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        storage = S3MediaStorage(bucket="test-bucket", presigned_url_expiry=7200)
        storage._client = mock_client

        storage.get_url("some/key.png", expires_in=60)
        assert mock_client.generate_presigned_url.call_args[1]["ExpiresIn"] == 60

        storage.get_url("some/key.png", expires_in=None)
        assert mock_client.generate_presigned_url.call_args[1]["ExpiresIn"] == 7200

    def test_get_url_expires_in_zero_is_taken_literally(self):
        """Only None means "use the configured expiry".

        An explicit 0 asks for an already-expired URL and must be passed through — a
        falsy-instead-of-None guard here would silently hand back a live one-hour URL.
        """
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        storage = S3MediaStorage(bucket="test-bucket", presigned_url_expiry=3600)
        storage._client = mock_client

        storage.get_url("some/key.png", expires_in=0)
        assert mock_client.generate_presigned_url.call_args[1]["ExpiresIn"] == 0

    def test_get_url_public(self):
        from agno.media.storage.s3 import S3MediaStorage

        storage = S3MediaStorage(bucket="test-bucket", region="us-west-2", acl="public-read")
        url = storage.get_url("some/key.png")

        assert "test-bucket" in url
        assert "us-west-2" in url
        assert "some/key.png" in url

    def test_exists_true(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        assert storage.exists("some/key.png") is True
        mock_client.head_object.assert_called_once()

    def test_exists_false(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        mock_client.head_object.side_effect = Exception("Not found")

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        assert storage.exists("nonexistent/key.png") is False

    def test_delete(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        assert storage.delete("some/key.png") is True
        mock_client.delete_object.assert_called_once()

    def test_backend_name(self):
        from agno.media.storage.s3 import S3MediaStorage

        storage = S3MediaStorage(bucket="test")
        assert storage.backend_name == "s3"

    def test_custom_endpoint(self):
        from agno.media.storage.s3 import S3MediaStorage

        storage = S3MediaStorage(
            bucket="test-bucket",
            endpoint_url="http://localhost:9000",
            acl="public-read",
        )
        url = storage.get_url("some/key.png")
        assert url.startswith("http://localhost:9000/")


class TestS3DeleteMany:
    def test_batches_into_one_call(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        mock_client.delete_objects.return_value = {}
        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client

        assert storage.delete_many(["a", "b", "c"]) == 3
        mock_client.delete_objects.assert_called_once_with(
            Bucket="test-bucket",
            Delete={"Objects": [{"Key": "a"}, {"Key": "b"}, {"Key": "c"}], "Quiet": True},
        )

    def test_splits_at_the_api_limit(self):
        """DeleteObjects rejects more than 1000 keys, so a larger sweep must be chunked."""
        from agno.media.storage.s3 import S3MediaStorage
        from agno.media.storage.s3.utils import S3_DELETE_BATCH_SIZE

        mock_client = MagicMock()
        mock_client.delete_objects.return_value = {}
        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client

        keys = [f"key-{i}" for i in range(S3_DELETE_BATCH_SIZE + 1)]
        assert storage.delete_many(keys) == S3_DELETE_BATCH_SIZE + 1
        assert mock_client.delete_objects.call_count == 2
        assert len(mock_client.delete_objects.call_args_list[0][1]["Delete"]["Objects"]) == S3_DELETE_BATCH_SIZE
        assert len(mock_client.delete_objects.call_args_list[1][1]["Delete"]["Objects"]) == 1

    def test_reported_errors_are_not_counted(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        mock_client.delete_objects.return_value = {"Errors": [{"Key": "b", "Code": "AccessDenied"}]}
        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client

        assert storage.delete_many(["a", "b", "c"]) == 2

    def test_a_failed_call_counts_nothing(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        mock_client.delete_objects.side_effect = RuntimeError("network down")
        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client

        assert storage.delete_many(["a", "b"]) == 0

    def test_empty_makes_no_call(self):
        from agno.media.storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client

        assert storage.delete_many([]) == 0
        mock_client.delete_objects.assert_not_called()


class TestClientConstructionFailures:
    """A backend whose client cannot be built answers like any other failure. S3 was the only
    one that raised out of exists()/delete(), where GCS and the local backend return False."""

    def _broken_storage(self):
        from agno.media.storage.s3 import S3MediaStorage

        storage = S3MediaStorage(bucket="test-bucket")
        storage._get_client = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
            ImportError("boto3 is required for S3MediaStorage.")
        )
        return storage

    def test_exists_returns_false(self):
        assert self._broken_storage().exists("agno/img.png") is False

    def test_delete_returns_false(self):
        assert self._broken_storage().delete("agno/img.png") is False

    def test_delete_many_returns_a_count(self):
        """base.py promises a count of what is gone, and its default implementation is a loop
        over delete(), which cannot raise. S3 overrides it for the batch API and was the only
        backend where a sweep would abort instead of logging and continuing."""
        assert self._broken_storage().delete_many(["agno/a.png", "agno/b.png"]) == 0

    @pytest.mark.asyncio
    async def test_async_exists_and_delete_return_false(self):
        from agno.media.storage.s3 import AsyncS3MediaStorage

        storage = AsyncS3MediaStorage(bucket="test-bucket")
        storage._get_session = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
            ImportError("aioboto3 is required for AsyncS3MediaStorage.")
        )

        assert await storage.exists("agno/img.png") is False
        assert await storage.delete("agno/img.png") is False
        assert await storage.delete_many(["agno/a.png", "agno/b.png"]) == 0


class TestPresignedExpiryCeiling:
    """SigV4 signs for at most seven days. boto3 does not check, so an expiry above the ceiling
    produced a URL that looked valid and was rejected on use, while GCS's library raised and the
    backend returned "" — the same misconfiguration degrading in opposite directions."""

    def _storage(self, expiry):
        from agno.media.storage.s3 import S3MediaStorage

        return S3MediaStorage(
            bucket="test-bucket",
            region="us-east-1",
            presigned_url_expiry=expiry,
            aws_access_key_id="AK",
            aws_secret_access_key="SK",
        )

    def test_url_signed_at_the_ceiling(self):
        from agno.media.storage.s3.utils import S3_MAX_PRESIGNED_EXPIRY

        assert self._storage(S3_MAX_PRESIGNED_EXPIRY).get_url("agno/k.png").startswith("https://")

    def test_no_url_past_the_ceiling(self):
        from agno.media.storage.s3.utils import S3_MAX_PRESIGNED_EXPIRY

        assert self._storage(S3_MAX_PRESIGNED_EXPIRY + 1).get_url("agno/k.png") is None

    @pytest.mark.asyncio
    async def test_async_no_url_past_the_ceiling(self):
        from agno.media.storage.s3 import AsyncS3MediaStorage
        from agno.media.storage.s3.utils import S3_MAX_PRESIGNED_EXPIRY

        storage = AsyncS3MediaStorage(bucket="test-bucket", presigned_url_expiry=S3_MAX_PRESIGNED_EXPIRY + 1)
        assert await storage.get_url("agno/k.png") is None


class TestSignatureVersion:
    def test_presigned_urls_use_sigv4(self):
        """Unpinned, botocore presigns with SigV2 in every region — not only the legacy
        us-east-1 case — and every region launched after January 2014 rejects it."""
        from urllib.parse import parse_qs, urlsplit

        from agno.media.storage.s3 import S3MediaStorage

        storage = S3MediaStorage(
            bucket="test-bucket", region="eu-west-1", aws_access_key_id="AK", aws_secret_access_key="SK"
        )
        params = parse_qs(urlsplit(storage.get_url("agno/k.png")).query)

        assert "X-Amz-Signature" in params
        assert "Signature" not in params

    @pytest.mark.asyncio
    async def test_async_presigned_urls_use_sigv4(self):
        from urllib.parse import parse_qs, urlsplit

        from agno.media.storage.s3 import AsyncS3MediaStorage

        storage = AsyncS3MediaStorage(
            bucket="test-bucket", region="eu-west-1", aws_access_key_id="AK", aws_secret_access_key="SK"
        )
        params = parse_qs(urlsplit(await storage.get_url("agno/k.png")).query)

        assert "X-Amz-Signature" in params
        assert "Signature" not in params


class TestAclConfigError:
    def test_acl_rejection_becomes_an_actionable_error(self):
        """The offload layer only logs upload failures, so the message has to carry the fix."""
        from agno.media.storage.s3.utils import raise_if_acl_unsupported

        client_error = pytest.importorskip("botocore.exceptions").ClientError
        error = client_error({"Error": {"Code": "AccessControlListNotSupported"}}, "PutObject")

        with pytest.raises(ValueError, match="does not allow ACLs"):
            raise_if_acl_unsupported(error, "my-bucket")

    def test_other_errors_pass_through_untouched(self):
        from agno.media.storage.s3.utils import raise_if_acl_unsupported

        client_error = pytest.importorskip("botocore.exceptions").ClientError
        raise_if_acl_unsupported(client_error({"Error": {"Code": "AccessDenied"}}, "PutObject"), "my-bucket")
        raise_if_acl_unsupported(RuntimeError("network down"), "my-bucket")

    def test_upload_surfaces_it(self):
        from agno.media.storage.s3 import S3MediaStorage

        client_error = pytest.importorskip("botocore.exceptions").ClientError
        mock_client = MagicMock()
        mock_client.put_object.side_effect = client_error(
            {"Error": {"Code": "AccessControlListNotSupported"}}, "PutObject"
        )
        storage = S3MediaStorage(bucket="my-bucket", acl="public-read")
        storage._client = mock_client

        with pytest.raises(ValueError, match="Drop the acl argument"):
            storage.upload("media-1", b"content", mime_type="image/png")


class TestMetadataSanitizing:
    def test_sanitize_s3_metadata(self):
        from agno.media.storage.s3.utils import sanitize_s3_metadata

        out = sanitize_s3_metadata({"caption": "héllo ☃", "dept": "finance", "big": "x" * 5000})
        assert "caption" not in out  # non-ASCII dropped
        assert out["dept"] == "finance"  # ASCII kept
        assert "big" not in out  # oversized dropped
        assert all(ord(c) < 128 for v in out.values() for c in v)

    def test_sanitize_s3_metadata_drops_control_characters(self):
        """S3 metadata rides in HTTP headers, so an ASCII newline still fails the whole upload."""
        from agno.media.storage.s3.utils import sanitize_s3_metadata

        out = sanitize_s3_metadata({"note": "line1\nline2", "ret": "a\rb", "nul": "a\x00b", "dept": "finance"})
        assert "note" not in out
        assert "ret" not in out
        assert "nul" not in out
        assert out["dept"] == "finance"  # siblings of a dropped entry survive
        # Tab is a legal header value character and S3 accepts it, so it is not over-restricted.
        assert sanitize_s3_metadata({"note": "a\tb"})["note"] == "a\tb"
