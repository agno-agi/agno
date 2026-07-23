"""Regression test for reviewer comment #9 on PR #8350.

``GcsJsonDb._write_json_file`` used to catch every exception, log it, and
``return`` — silently succeeding from the caller's view while the write
actually failed. That means credential expiry, quota exhaustion, or network
outage produced silent data loss.

``_read_json_file`` had a related smell: it string-matched ``"404"`` in the
exception message (fragile) and remapped every other error to
``JSONDecodeError`` (misleading — the file might not have been corrupt).

These tests use mocks so we don't need a real GCS bucket.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_db_with_mock_bucket() -> tuple:
    """Instantiate GcsJsonDb without touching real GCS (bypass __init__)."""
    try:
        from agno.db.gcs_json.gcs_json_db import GcsJsonDb
    except ImportError:
        pytest.skip("google-cloud-storage not installed")

    # Bypass __init__ so we don't need real credentials
    db = GcsJsonDb.__new__(GcsJsonDb)
    bucket = MagicMock()
    db.bucket = bucket
    db.prefix = "test"
    return db, bucket


class TestWriteJsonFilePropagatesFailures:
    def test_write_propagates_gcs_upload_error(self):
        db, bucket = _make_db_with_mock_bucket()
        blob = MagicMock()
        bucket.blob.return_value = blob
        blob.upload_from_string.side_effect = RuntimeError("simulated GCS quota exhausted")

        with pytest.raises(RuntimeError, match="quota exhausted"):
            db._write_json_file("sessions", [{"a": 1}])

    def test_write_success_returns_normally(self):
        db, bucket = _make_db_with_mock_bucket()
        blob = MagicMock()
        bucket.blob.return_value = blob
        # No exception → returns None quietly
        result = db._write_json_file("sessions", [{"a": 1}])
        assert result is None
        blob.upload_from_string.assert_called_once()


class TestReadJsonFileNotFoundUsesTypedException:
    def test_not_found_returns_empty_when_create_true(self):
        try:
            from google.cloud.exceptions import NotFound  # type: ignore[import-untyped]
        except ImportError:
            pytest.skip("google-cloud-exceptions not installed")

        db, bucket = _make_db_with_mock_bucket()
        blob = MagicMock()
        bucket.blob.return_value = blob
        blob.download_as_bytes.side_effect = NotFound("blob missing")

        result = db._read_json_file("sessions", create_table_if_not_found=True)
        assert result == []
        blob.upload_from_string.assert_called_once_with("[]", content_type="application/json")

    def test_not_found_returns_empty_when_create_false(self):
        try:
            from google.cloud.exceptions import NotFound  # type: ignore[import-untyped]
        except ImportError:
            pytest.skip("google-cloud-exceptions not installed")

        db, bucket = _make_db_with_mock_bucket()
        blob = MagicMock()
        bucket.blob.return_value = blob
        blob.download_as_bytes.side_effect = NotFound("blob missing")

        result = db._read_json_file("sessions", create_table_if_not_found=False)
        assert result == []
        blob.upload_from_string.assert_not_called()


class TestReadJsonFileGenericErrorPropagates:
    def test_permission_error_propagates(self):
        db, bucket = _make_db_with_mock_bucket()
        blob = MagicMock()
        bucket.blob.return_value = blob
        # Any non-NotFound exception (e.g. permission denied, network)
        blob.download_as_bytes.side_effect = PermissionError("no perms")

        with pytest.raises(PermissionError):
            db._read_json_file("sessions", create_table_if_not_found=False)

    def test_malformed_json_raises_json_decode_error(self):
        db, bucket = _make_db_with_mock_bucket()
        blob = MagicMock()
        bucket.blob.return_value = blob
        blob.download_as_bytes.return_value = b"not valid json {"

        import json as _json

        with pytest.raises(_json.JSONDecodeError):
            db._read_json_file("sessions", create_table_if_not_found=False)


class TestReadSuccessPathStillWorks:
    def test_valid_json_returns_data(self):
        db, bucket = _make_db_with_mock_bucket()
        blob = MagicMock()
        bucket.blob.return_value = blob
        blob.download_as_bytes.return_value = b'[{"a": 1}, {"a": 2}]'

        result = db._read_json_file("sessions", create_table_if_not_found=False)
        assert result == [{"a": 1}, {"a": 2}]
