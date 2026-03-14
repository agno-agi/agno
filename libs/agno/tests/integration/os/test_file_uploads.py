"""Integration tests for file uploads with files_metadata on agent and team endpoints."""

import json
from unittest.mock import AsyncMock, patch

from agno.agent.agent import Agent
from agno.media import File as FileMedia
from agno.media import Image
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockRunOutput:
    def to_dict(self):
        return {}


# ---------------------------------------------------------------------------
# Agent endpoint — file uploads
# ---------------------------------------------------------------------------


class TestAgentFileUploads:
    def _post_agent_files(self, client, agent_id, files, files_metadata=None):
        """Helper to POST multipart files to the agent run endpoint."""
        data = {"message": "test", "stream": "false"}
        if files_metadata is not None:
            data["files_metadata"] = files_metadata
        return client.post(f"/agents/{agent_id}/runs", data=data, files=files)

    def test_upload_image_no_metadata(self, test_os_client, test_agent: Agent):
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            files = [("files", ("photo.png", b"fake-png-bytes", "image/png"))]

            resp = self._post_agent_files(test_os_client, test_agent.id, files)

            assert resp.status_code == 200
            call_args = mock_arun.call_args
            images = call_args.kwargs.get("images")
            assert images is not None and len(images) == 1
            assert isinstance(images[0], Image)
            assert images[0].metadata is None

    def test_upload_image_with_metadata(self, test_os_client, test_agent: Agent):
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            meta = [{"source": "webcam", "tag": "profile"}]
            files = [("files", ("photo.png", b"fake-png-bytes", "image/png"))]

            resp = self._post_agent_files(test_os_client, test_agent.id, files, json.dumps(meta))

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs["images"]
            assert images[0].metadata == {"source": "webcam", "tag": "profile"}

    def test_upload_multiple_files_with_positional_metadata(self, test_os_client, test_agent: Agent):
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            meta = [{"idx": 0}, {"idx": 1}, {"idx": 2}]
            files = [
                ("files", ("img.png", b"png-data", "image/png")),
                ("files", ("clip.wav", b"wav-data", "audio/wav")),
                ("files", ("doc.pdf", b"pdf-data", "application/pdf")),
            ]

            resp = self._post_agent_files(test_os_client, test_agent.id, files, json.dumps(meta))

            assert resp.status_code == 200
            call_kw = mock_arun.call_args.kwargs
            assert call_kw["images"][0].metadata == {"idx": 0}
            assert call_kw["audio"][0].metadata == {"idx": 1}
            assert call_kw["files"][0].metadata == {"idx": 2}

    def test_upload_files_metadata_shorter_than_files(self, test_os_client, test_agent: Agent):
        """When fewer metadata entries than files, extra files get None."""
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            meta = [{"first": True}, {"second": True}]
            files = [
                ("files", ("a.png", b"png", "image/png")),
                ("files", ("b.png", b"png", "image/png")),
                ("files", ("c.png", b"png", "image/png")),
            ]

            resp = self._post_agent_files(test_os_client, test_agent.id, files, json.dumps(meta))

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs["images"]
            assert images[0].metadata == {"first": True}
            assert images[1].metadata == {"second": True}
            assert images[2].metadata is None

    def test_upload_files_metadata_empty_array(self, test_os_client, test_agent: Agent):
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            files = [("files", ("photo.png", b"data", "image/png"))]

            resp = self._post_agent_files(test_os_client, test_agent.id, files, "[]")

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs["images"]
            assert images[0].metadata is None

    def test_upload_files_metadata_invalid_json(self, test_os_client, test_agent: Agent):
        """Invalid JSON is ignored gracefully — metadata is None."""
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            files = [("files", ("photo.png", b"data", "image/png"))]

            resp = self._post_agent_files(test_os_client, test_agent.id, files, "not-valid-json")

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs["images"]
            assert images[0].metadata is None

    def test_upload_files_metadata_not_a_list(self, test_os_client, test_agent: Agent):
        """Non-list JSON is ignored — metadata stays None."""
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            files = [("files", ("photo.png", b"data", "image/png"))]

            resp = self._post_agent_files(test_os_client, test_agent.id, files, '{"key":"val"}')

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs["images"]
            assert images[0].metadata is None

    def test_upload_files_metadata_with_null_entries(self, test_os_client, test_agent: Agent):
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            meta = [None, {"tag": "x"}]
            files = [
                ("files", ("a.png", b"data", "image/png")),
                ("files", ("b.png", b"data", "image/png")),
            ]

            resp = self._post_agent_files(test_os_client, test_agent.id, files, json.dumps(meta))

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs["images"]
            assert images[0].metadata is None
            assert images[1].metadata == {"tag": "x"}

    def test_upload_unsupported_file_type(self, test_os_client, test_agent: Agent):
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            files = [("files", ("data.xyz", b"something", "application/octet-stream"))]

            resp = self._post_agent_files(test_os_client, test_agent.id, files)

            assert resp.status_code == 400

    def test_upload_document_file(self, test_os_client, test_agent: Agent):
        with (
            patch.object(test_agent, "deep_copy", return_value=test_agent),
            patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            meta = [{"category": "legal"}]
            files = [("files", ("contract.pdf", b"%PDF-1.4-fake", "application/pdf"))]

            resp = self._post_agent_files(test_os_client, test_agent.id, files, json.dumps(meta))

            assert resp.status_code == 200
            docs = mock_arun.call_args.kwargs["files"]
            assert len(docs) == 1
            assert isinstance(docs[0], FileMedia)
            assert docs[0].filename == "contract.pdf"
            assert docs[0].metadata == {"category": "legal"}


# ---------------------------------------------------------------------------
# Team endpoint — file uploads
# ---------------------------------------------------------------------------


class TestTeamFileUploads:
    def _post_team_files(self, client, team_id, files, files_metadata=None):
        """Helper to POST multipart files to the team run endpoint."""
        data = {"message": "test", "stream": "false"}
        if files_metadata is not None:
            data["files_metadata"] = files_metadata
        return client.post(f"/teams/{team_id}/runs", data=data, files=files)

    def test_team_upload_image_no_metadata(self, test_os_client, test_team: Team):
        with (
            patch.object(test_team, "deep_copy", return_value=test_team),
            patch.object(test_team, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            files = [("files", ("photo.png", b"fake-png-bytes", "image/png"))]

            resp = self._post_team_files(test_os_client, test_team.id, files)

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs.get("images")
            assert images is not None and len(images) == 1
            assert isinstance(images[0], Image)
            assert images[0].metadata is None

    def test_team_upload_image_with_metadata(self, test_os_client, test_team: Team):
        with (
            patch.object(test_team, "deep_copy", return_value=test_team),
            patch.object(test_team, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            meta = [{"source": "drone"}]
            files = [("files", ("photo.png", b"fake-png-bytes", "image/png"))]

            resp = self._post_team_files(test_os_client, test_team.id, files, json.dumps(meta))

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs["images"]
            assert images[0].metadata == {"source": "drone"}

    def test_team_upload_files_metadata_shorter_than_files(self, test_os_client, test_team: Team):
        with (
            patch.object(test_team, "deep_copy", return_value=test_team),
            patch.object(test_team, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            meta = [{"first": True}]
            files = [
                ("files", ("a.png", b"png", "image/png")),
                ("files", ("b.png", b"png", "image/png")),
            ]

            resp = self._post_team_files(test_os_client, test_team.id, files, json.dumps(meta))

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs["images"]
            assert images[0].metadata == {"first": True}
            assert images[1].metadata is None

    def test_team_upload_files_metadata_invalid_json(self, test_os_client, test_team: Team):
        with (
            patch.object(test_team, "deep_copy", return_value=test_team),
            patch.object(test_team, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            files = [("files", ("photo.png", b"data", "image/png"))]

            resp = self._post_team_files(test_os_client, test_team.id, files, "broken{json")

            assert resp.status_code == 200
            images = mock_arun.call_args.kwargs["images"]
            assert images[0].metadata is None

    def test_team_upload_document_with_metadata(self, test_os_client, test_team: Team):
        with (
            patch.object(test_team, "deep_copy", return_value=test_team),
            patch.object(test_team, "arun", new_callable=AsyncMock) as mock_arun,
        ):
            mock_arun.return_value = MockRunOutput()
            meta = [{"category": "report"}]
            files = [("files", ("report.pdf", b"%PDF-fake", "application/pdf"))]

            resp = self._post_team_files(test_os_client, test_team.id, files, json.dumps(meta))

            assert resp.status_code == 200
            docs = mock_arun.call_args.kwargs["files"]
            assert len(docs) == 1
            assert isinstance(docs[0], FileMedia)
            assert docs[0].filename == "report.pdf"
            assert docs[0].metadata == {"category": "report"}
