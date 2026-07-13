"""Integration tests for media passed as JSON form fields to the run endpoints.

AgnoClient (used by the Team API to delegate to a RemoteAgent member) sends media as JSON form fields with base64-encoded
RemoteAgent/RemoteTeam members) sends media as JSON form fields with base64-encoded
content, the format produced by Image/Audio/Video/File.to_dict(). The run endpoints must
reconstruct these into media objects and pass them to the run — previously the raw JSON
string collided with the explicit media kwargs and the media never reached the agent.
"""

import json
import struct
import zlib

from agno.agent.agent import Agent
from agno.media import Image
from agno.team.team import Team


def make_png(width: int = 64, height: int = 64, rgb: tuple = (255, 0, 0)) -> bytes:
    """Build a solid-color PNG in pure Python (no pillow dependency)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * width
    idat = zlib.compress(row * height)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def red_image_form_field() -> str:
    """Serialize a red image exactly like AgnoClient.run_agent/run_team do."""
    image = Image(content=make_png(rgb=(255, 0, 0)), format="png", mime_type="image/png")
    return json.dumps([image.to_dict()])


def test_agent_run_with_images_form_field(test_os_client, test_agent: Agent):
    """An images JSON form field (AgnoClient wire format) reaches the agent."""
    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "What is the dominant color of the attached image? Answer with the color name only.",
            "stream": "false",
            "images": red_image_form_field(),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["run_id"] is not None
    assert "red" in str(response_json["content"]).lower()


def test_agent_run_streaming_with_images_form_field(test_os_client, test_agent: Agent):
    """Same as above via the streaming path."""
    with test_os_client.stream(
        "POST",
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "What is the dominant color of the attached image? Answer with the color name only.",
            "stream": "true",
            "images": red_image_form_field(),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        assert response.status_code == 200

        content = ""
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data != "[DONE]":
                    content += json.loads(data).get("content") or ""

    assert "red" in content.lower()


def test_team_run_with_images_form_field(test_os_client, test_team: Team):
    """An images JSON form field reaches the team run."""
    response = test_os_client.post(
        f"/teams/{test_team.id}/runs",
        data={
            "message": "What is the dominant color of the attached image? Answer with the color name only.",
            "stream": "false",
            "images": red_image_form_field(),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["run_id"] is not None
    assert "red" in str(response_json["content"]).lower()


def test_agent_run_with_invalid_images_form_field(test_os_client, test_agent: Agent):
    """An unparseable images field is dropped with a warning instead of failing the run."""
    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Hello, world!",
            "stream": "false",
            "images": "not-valid-json",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert response.json()["content"] is not None
