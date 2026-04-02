from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.run.agent import RunOutput


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.id = "test-agent"
    return agent


@pytest.fixture
def mock_team():
    team = MagicMock()
    team.id = "test-team"
    return team


@pytest.mark.asyncio
async def test_agent_run_upload_image_success(test_os_client, mock_agent):
    """Test successful image upload to agent run endpoint."""
    file_content = b"fake image content"
    files = {"files": ("test.png", BytesIO(file_content), "image/png")}
    data = {"message": "analyze this image", "stream": "false"}

    # Mocking process_image and get_agent_by_id
    with (
        patch("agno.os.routers.agents.router.process_image", return_value={"url": "mock_url"}),
        patch("agno.os.routers.agents.router.get_agent_by_id", return_value=mock_agent),
        patch.object(mock_agent, "arun", new_callable=AsyncMock) as mock_arun,
    ):
        mock_arun.return_value = RunOutput(run_id="123", content="ok")

        response = test_os_client.post(f"/agents/{mock_agent.id}/runs", data=data, files=files)

        assert response.status_code == 200
        assert "run_id" in response.json()


@pytest.mark.asyncio
async def test_agent_run_upload_unsupported_file_fails(test_os_client, mock_agent):
    """Test that unsupported file types are rejected early by the router."""
    file_content = b"echo 'malicious'"
    files = {"files": ("attack.sh", BytesIO(file_content), "application/x-sh")}
    data = {"message": "run this script", "stream": "false"}

    with patch("agno.os.routers.agents.router.get_agent_by_id", return_value=mock_agent):
        response = test_os_client.post(f"/agents/{mock_agent.id}/runs", data=data, files=files)

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported file type"


@pytest.mark.asyncio
async def test_team_run_upload_multiple_media_success(test_os_client, mock_team):
    """Test multiple media uploads (Image + File) to team run endpoint."""
    image_content = b"fake image"
    zip_content = b"fake zip"

    files = [
        ("files", ("img.png", BytesIO(image_content), "image/png")),
        ("files", ("data.zip", BytesIO(zip_content), "application/zip")),
    ]
    data = {"message": "process these", "stream": "false"}

    with (
        patch("agno.os.routers.teams.router.process_image", return_value={"url": "img_url"}),
        patch("agno.os.routers.teams.router.process_document", return_value={"url": "zip_url"}),
        patch("agno.os.routers.teams.router.get_team_by_id", return_value=mock_team),
        patch.object(mock_team, "arun", new_callable=AsyncMock) as mock_arun,
    ):
        mock_arun.return_value = RunOutput(run_id="team-123", content="processed")

        response = test_os_client.post(f"/teams/{mock_team.id}/runs", data=data, files=files)

        assert response.status_code == 200
        assert response.json()["run_id"] == "team-123"


@pytest.mark.asyncio
async def test_agent_run_upload_svg_success(test_os_client, mock_agent):
    """Test that the new SVG support is working in the router."""
    file_content = b"<svg>...</svg>"
    files = {"files": ("logo.svg", BytesIO(file_content), "image/svg+xml")}
    data = {"message": "analyze svg", "stream": "false"}

    with (
        patch("agno.os.routers.agents.router.process_image", return_value={"url": "svg_url"}),
        patch("agno.os.routers.agents.router.get_agent_by_id", return_value=mock_agent),
        patch.object(mock_agent, "arun", new_callable=AsyncMock) as mock_arun,
    ):
        mock_arun.return_value = RunOutput(run_id="svg-123", content="ok")

        response = test_os_client.post(f"/agents/{mock_agent.id}/runs", data=data, files=files)

        assert response.status_code == 200
