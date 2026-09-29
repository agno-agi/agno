"""Tests that remote loaders keep the owner on the per-file entries of a folder upload."""

from types import SimpleNamespace

import pytest

from agno.knowledge.content import Content
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content.remote_content import GCSContent, S3Content


@pytest.fixture
def knowledge():
    # Knowledge inherits from every provider loader, so it is the loader under test.
    return Knowledge()


def _capture_entries(knowledge, skip_owners=None):
    """Collect the entries a loader writes, short-circuiting the read/embed work.

    ``skip_owners``, when given, records the owner each ``_should_skip`` call is scoped to.
    """
    captured = []

    async def _acapture(entry):
        captured.append(entry)

    async def _anoop(entry):
        return None

    def _should_skip(content_hash, skip_if_exists, user_id=None, prior_status=None):
        if skip_owners is not None:
            skip_owners.append(user_id)
        return True

    knowledge._insert_contents_db = lambda entry: captured.append(entry)
    knowledge._ainsert_contents_db = _acapture
    knowledge._should_skip = _should_skip
    knowledge._update_content = lambda entry: None
    knowledge._aupdate_content = _anoop
    return captured


class TestFolderEntryOwner:
    """The shared helper behind the github, sharepoint and azure_blob loaders."""

    def test_folder_entry_inherits_owner(self, knowledge):
        parent = Content(name="reports", path="gh://org/repo/reports", user_id="alice")

        entry = knowledge._create_content_entry_for_folder(
            parent, "reports/q1.pdf", "gh://org/repo/reports/q1.pdf", {}, "github"
        )

        assert entry.user_id == "alice"

    def test_unowned_folder_entry_stays_unowned(self, knowledge):
        """Isolation off / admin uploads still produce shared rows."""
        parent = Content(name="reports", path="gh://org/repo/reports")

        entry = knowledge._create_content_entry_for_folder(
            parent, "reports/q1.pdf", "gh://org/repo/reports/q1.pdf", {}, "github"
        )

        assert entry.user_id is None

    def test_two_owners_get_distinct_ids_for_the_same_file(self, knowledge):
        """The id is derived from the hash, so a shared owner would collapse the rows."""
        alice = Content(name="reports", path="gh://org/repo/reports", user_id="alice")
        bob = Content(name="reports", path="gh://org/repo/reports", user_id="bob")

        alice_entry = knowledge._create_content_entry_for_folder(
            alice, "reports/q1.pdf", "gh://org/repo/reports/q1.pdf", {}, "github"
        )
        bob_entry = knowledge._create_content_entry_for_folder(
            bob, "reports/q1.pdf", "gh://org/repo/reports/q1.pdf", {}, "github"
        )

        assert alice_entry.id != bob_entry.id


def _s3_content():
    bucket = SimpleNamespace(
        name="private-bucket",
        get_objects=lambda prefix: [
            SimpleNamespace(name="alice/q1.pdf", uri="s3://private-bucket/alice/q1.pdf"),
            SimpleNamespace(name="alice/q2.pdf", uri="s3://private-bucket/alice/q2.pdf"),
        ],
    )
    return Content(name="my-reports", user_id="alice", remote_content=S3Content(bucket=bucket, prefix="alice/"))


def _gcs_content():
    blobs = [
        SimpleNamespace(name="alice/q1.pdf", download_as_bytes=lambda: b""),
        SimpleNamespace(name="alice/q2.pdf", download_as_bytes=lambda: b""),
    ]
    bucket = SimpleNamespace(name="private-bucket", list_blobs=lambda prefix: blobs)
    return Content(name="my-reports", user_id="alice", remote_content=GCSContent(bucket=bucket, prefix="alice/"))


class TestS3FolderOwner:
    def test_s3_folder_entries_inherit_owner(self, knowledge):
        captured = _capture_entries(knowledge)

        knowledge._load_from_s3(_s3_content(), upsert=False, skip_if_exists=True, config=None)

        assert len(captured) == 2
        assert [entry.user_id for entry in captured] == ["alice", "alice"]

    @pytest.mark.asyncio
    async def test_async_s3_folder_entries_inherit_owner(self, knowledge):
        captured = _capture_entries(knowledge)

        await knowledge._aload_from_s3(_s3_content(), upsert=False, skip_if_exists=True, config=None)

        assert len(captured) == 2
        assert [entry.user_id for entry in captured] == ["alice", "alice"]


class TestGCSFolderOwner:
    def test_gcs_folder_entries_inherit_owner(self, knowledge):
        captured = _capture_entries(knowledge)

        knowledge._load_from_gcs(_gcs_content(), upsert=False, skip_if_exists=True, config=None)

        assert len(captured) == 2
        assert [entry.user_id for entry in captured] == ["alice", "alice"]

    @pytest.mark.asyncio
    async def test_async_gcs_folder_entries_inherit_owner(self, knowledge):
        captured = _capture_entries(knowledge)

        await knowledge._aload_from_gcs(_gcs_content(), upsert=False, skip_if_exists=True, config=None)

        assert len(captured) == 2
        assert [entry.user_id for entry in captured] == ["alice", "alice"]


class TestSkipCheckIsOwnerScoped:
    """``_should_skip`` defaults to the shared bucket, so an unscoped check never matches an owned row."""

    def test_s3_skip_check_is_scoped_to_the_owner(self, knowledge):
        skip_owners: list = []
        _capture_entries(knowledge, skip_owners)

        knowledge._load_from_s3(_s3_content(), upsert=False, skip_if_exists=True, config=None)

        assert skip_owners == ["alice", "alice"]

    @pytest.mark.asyncio
    async def test_async_s3_skip_check_is_scoped_to_the_owner(self, knowledge):
        skip_owners: list = []
        _capture_entries(knowledge, skip_owners)

        await knowledge._aload_from_s3(_s3_content(), upsert=False, skip_if_exists=True, config=None)

        assert skip_owners == ["alice", "alice"]

    def test_gcs_skip_check_is_scoped_to_the_owner(self, knowledge):
        skip_owners: list = []
        _capture_entries(knowledge, skip_owners)

        knowledge._load_from_gcs(_gcs_content(), upsert=False, skip_if_exists=True, config=None)

        assert skip_owners == ["alice", "alice"]

    @pytest.mark.asyncio
    async def test_async_gcs_skip_check_is_scoped_to_the_owner(self, knowledge):
        skip_owners: list = []
        _capture_entries(knowledge, skip_owners)

        await knowledge._aload_from_gcs(_gcs_content(), upsert=False, skip_if_exists=True, config=None)

        assert skip_owners == ["alice", "alice"]

    def test_unowned_sync_still_checks_the_shared_bucket(self, knowledge):
        """Isolation off / admin syncs keep the old behaviour."""
        skip_owners: list = []
        _capture_entries(knowledge, skip_owners)
        content = _s3_content()
        content.user_id = None

        knowledge._load_from_s3(content, upsert=False, skip_if_exists=True, config=None)

        assert skip_owners == [None, None]
