"""Tests for S3MediaStorage with mocked boto3."""

from unittest.mock import MagicMock


class TestS3MediaStorage:
    def test_upload(self):
        from agno.media_storage.s3 import S3MediaStorage

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
        from agno.media_storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"file-content"
        mock_client.get_object.return_value = {"Body": mock_body}

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        result = storage.download("some/key.png")

        assert result == b"file-content"
        mock_client.get_object.assert_called_once_with(Bucket="test-bucket", Key="some/key.png")

    def test_get_url_presigned(self):
        from agno.media_storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://presigned.example.com"

        storage = S3MediaStorage(bucket="test-bucket", presigned_url_expiry=7200)
        storage._client = mock_client
        url = storage.get_url("some/key.png")

        assert url == "https://presigned.example.com"
        mock_client.generate_presigned_url.assert_called_once()

    def test_get_url_public(self):
        from agno.media_storage.s3 import S3MediaStorage

        storage = S3MediaStorage(bucket="test-bucket", region="us-west-2", acl="public-read")
        url = storage.get_url("some/key.png")

        assert "test-bucket" in url
        assert "us-west-2" in url
        assert "some/key.png" in url

    def test_exists_true(self):
        from agno.media_storage.s3 import S3MediaStorage

        mock_client = MagicMock()

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        assert storage.exists("some/key.png") is True
        mock_client.head_object.assert_called_once()

    def test_exists_false(self):
        from agno.media_storage.s3 import S3MediaStorage

        mock_client = MagicMock()
        mock_client.head_object.side_effect = Exception("Not found")

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        assert storage.exists("nonexistent/key.png") is False

    def test_delete(self):
        from agno.media_storage.s3 import S3MediaStorage

        mock_client = MagicMock()

        storage = S3MediaStorage(bucket="test-bucket")
        storage._client = mock_client
        assert storage.delete("some/key.png") is True
        mock_client.delete_object.assert_called_once()

    def test_backend_name(self):
        from agno.media_storage.s3 import S3MediaStorage

        storage = S3MediaStorage(bucket="test")
        assert storage.backend_name == "s3"

    def test_custom_endpoint(self):
        from agno.media_storage.s3 import S3MediaStorage

        storage = S3MediaStorage(
            bucket="test-bucket",
            endpoint_url="http://localhost:9000",
            acl="public-read",
        )
        url = storage.get_url("some/key.png")
        assert url.startswith("http://localhost:9000/")
