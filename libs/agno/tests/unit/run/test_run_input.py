import base64
import json

import pytest

from agno.media import Image
from agno.models.message import Message
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput


def test_media_in_dict_input():
    """Test RunInput handles media when input_content is a list of dicts"""
    # Ensure the RunInput is created successfully
    run_input = RunInput(
        input_content=[
            {
                "role": "user",
                "content": "Hello, world!",
                "images": [Image(filepath="test.png")],
            }
        ]
    )

    # Assert the conversion to dict is successful
    run_input_dict = run_input.to_dict()
    assert run_input_dict["input_content"][0].get("images") is not None
    assert run_input_dict["input_content"][0].get("images")[0]["filepath"] == "test.png"


def test_media_in_message_input():
    """Test RunInput handles media when input_content is a list of Message objects"""
    # Ensure the RunInput is created successfully
    run_input = RunInput(
        input_content=[
            Message(role="user", content="Hello, world!", images=[Image(filepath="test.png")]),
        ]
    )

    # Assert the conversion to dict is successful
    run_input_dict = run_input.to_dict()
    assert run_input_dict["input_content"][0].get("images") is not None
    assert run_input_dict["input_content"][0].get("images")[0]["filepath"] == "test.png"


def test_media_in_dict_input_for_team():
    """Test TeamRunInput handles media when input_content is a list of dicts for Team"""
    # Ensure the TeamRunInput is created successfully
    team_run_input = TeamRunInput(
        input_content=[
            {
                "role": "user",
                "content": "Hello, world!",
                "images": [Image(filepath="test.png")],
            }
        ]
    )

    # Assert the conversion to dict is successful
    team_run_input_dict = team_run_input.to_dict()
    assert team_run_input_dict["input_content"][0].get("images") is not None
    assert team_run_input_dict["input_content"][0].get("images")[0]["filepath"] == "test.png"


def test_media_in_message_input_for_team():
    """Test TeamRunInput handles media when input_content is a list of Message objects"""
    # Ensure the TeamRunInput is created successfully
    team_run_input = TeamRunInput(
        input_content=[
            Message(role="user", content="Hello, world!", images=[Image(filepath="test.png")]),
        ]
    )

    # Assert the conversion to dict is successful
    team_run_input_dict = team_run_input.to_dict()
    assert team_run_input_dict["input_content"][0].get("images") is not None
    assert team_run_input_dict["input_content"][0].get("images")[0]["filepath"] == "test.png"


def test_mixed_dict_and_message_input_is_json_serializable():
    run_input = RunInput(
        input_content=[
            {"role": "user", "content": "Hello, world!"},
            Message(role="assistant", content="Hi!"),
        ]
    )

    run_input_dict = run_input.to_dict()
    json.dumps(run_input_dict)
    assert isinstance(run_input_dict["input_content"][1], dict)


def test_mixed_dict_and_message_input_is_json_serializable_for_team():
    team_run_input = TeamRunInput(
        input_content=[
            {"role": "user", "content": "Hello, world!"},
            Message(role="assistant", content="Hi!"),
        ]
    )

    team_run_input_dict = team_run_input.to_dict()
    json.dumps(team_run_input_dict)
    assert isinstance(team_run_input_dict["input_content"][1], dict)


def test_mixed_list_input_content_string_is_json():
    run_input = RunInput(
        input_content=[
            Message(role="user", content="Hello, world!"),
            {"role": "assistant", "content": "Hi!"},
        ]
    )

    data = json.loads(run_input.input_content_string())
    assert isinstance(data, list)
    assert isinstance(data[0], dict)
    assert isinstance(data[1], dict)


def test_mixed_list_input_content_string_is_json_for_team():
    team_run_input = TeamRunInput(
        input_content=[
            Message(role="user", content="Hello, world!"),
            {"role": "assistant", "content": "Hi!"},
        ]
    )

    data = json.loads(team_run_input.input_content_string())
    assert isinstance(data, list)
    assert isinstance(data[0], dict)
    assert isinstance(data[1], dict)


PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


@pytest.mark.parametrize("input_cls", [RunInput, TeamRunInput])
def test_message_input_with_image_bytes_is_json(input_cls):
    run_input = input_cls(
        input_content=Message(role="user", content="Describe this", images=[Image(content=PNG_BYTES)])
    )

    data = json.loads(run_input.input_content_string())
    assert data["content"] == "Describe this"
    assert data["images"][0]["content"] == base64.b64encode(PNG_BYTES).decode("utf-8")

    stored = json.loads(json.dumps(run_input.to_dict()))
    assert stored["input_content"]["images"][0]["content"] == base64.b64encode(PNG_BYTES).decode("utf-8")


@pytest.mark.parametrize("input_cls", [RunInput, TeamRunInput])
def test_message_input_matches_single_item_list(input_cls):
    message = Message(role="user", content="Describe this", images=[Image(content=PNG_BYTES)])

    single = json.loads(input_cls(input_content=message).input_content_string())
    listed = json.loads(input_cls(input_content=[message]).input_content_string())
    assert single == listed[0]
