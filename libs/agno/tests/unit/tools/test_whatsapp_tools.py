import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.whatsapp import WhatsAppTools

ENV = {
    "WHATSAPP_ACCESS_TOKEN": "test-token",
    "WHATSAPP_PHONE_NUMBER_ID": "123456",
}


@pytest.fixture
def whatsapp_tools():
    with patch.dict("os.environ", ENV):
        with patch("agno.tools.whatsapp.httpx") as mock_httpx:
            mock_response = Mock()
            mock_response.json.return_value = {"messages": [{"id": "wamid.test123"}]}
            mock_response.raise_for_status = Mock()
            mock_httpx.post.return_value = mock_response
            tools = WhatsAppTools(all=True, recipient_waid="+1234567890")
            tools._mock_httpx = mock_httpx
            yield tools


# === Initialization ===


def test_init_requires_access_token():
    with patch.dict("os.environ", {"WHATSAPP_PHONE_NUMBER_ID": "123"}, clear=True):
        with pytest.raises(ValueError, match="WHATSAPP_ACCESS_TOKEN"):
            WhatsAppTools()


def test_init_requires_phone_number_id():
    with patch.dict("os.environ", {"WHATSAPP_ACCESS_TOKEN": "tok"}, clear=True):
        with pytest.raises(ValueError, match="WHATSAPP_PHONE_NUMBER_ID"):
            WhatsAppTools()


def test_init_registers_default_tools():
    with patch.dict("os.environ", ENV):
        tools = WhatsAppTools()
        names = [f.name for f in tools.functions.values()]
        assert "send_text_message" in names
        assert "send_template_message" in names
        assert len(names) == 2


def test_init_all_flag_enables_all():
    with patch.dict("os.environ", ENV):
        tools = WhatsAppTools(all=True)
        assert len(tools.functions) == 9


def test_init_selective_enable():
    with patch.dict("os.environ", ENV):
        tools = WhatsAppTools(enable_send_image=True, enable_send_location=True)
        names = [f.name for f in tools.functions.values()]
        assert "send_text_message" in names
        assert "send_image" in names
        assert "send_location" in names
        assert len(names) == 4


# === Core Tools ===


def test_send_text_message(whatsapp_tools):
    result = whatsapp_tools.send_text_message(text="Hello", recipient="+1234567890")
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["message_id"] == "wamid.test123"


def test_send_text_message_default_recipient(whatsapp_tools):
    result = whatsapp_tools.send_text_message(text="Hello")
    parsed = json.loads(result)
    assert parsed["ok"] is True


def test_send_text_message_no_recipient():
    with patch.dict("os.environ", ENV):
        with patch("agno.tools.whatsapp.httpx"):
            tools = WhatsAppTools()
            result = tools.send_text_message(text="Hello")
            parsed = json.loads(result)
            assert "error" in parsed
            assert "recipient" in parsed["error"].lower()


def test_send_text_message_error(whatsapp_tools):
    whatsapp_tools._mock_httpx.post.side_effect = Exception("API error")
    result = whatsapp_tools.send_text_message(text="Hello", recipient="+1234567890")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "API error" in parsed["error"]


def test_send_template_message(whatsapp_tools):
    result = whatsapp_tools.send_template_message(template_name="hello_world", recipient="+1234567890")
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["message_id"] == "wamid.test123"


def test_send_template_message_with_components(whatsapp_tools):
    components = [{"type": "body", "parameters": [{"type": "text", "text": "World"}]}]
    result = whatsapp_tools.send_template_message(
        template_name="hello_world",
        recipient="+1234567890",
        components=components,
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["template"]["components"] == components


# === New Tools ===


def test_send_reply_buttons(whatsapp_tools):
    buttons = [
        {"id": "btn_yes", "title": "Yes"},
        {"id": "btn_no", "title": "No"},
    ]
    result = whatsapp_tools.send_reply_buttons(body_text="Do you agree?", buttons=buttons, recipient="+1234567890")
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "button"
    assert len(payload["interactive"]["action"]["buttons"]) == 2


def test_send_reply_buttons_max_3(whatsapp_tools):
    buttons = [{"id": f"btn_{i}", "title": f"Btn {i}"} for i in range(4)]
    result = whatsapp_tools.send_reply_buttons(body_text="Too many", buttons=buttons, recipient="+1234567890")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "maximum of 3" in parsed["error"]


def test_send_reply_buttons_with_header_footer(whatsapp_tools):
    buttons = [{"id": "btn_1", "title": "OK"}]
    result = whatsapp_tools.send_reply_buttons(
        body_text="Body", buttons=buttons, recipient="+1234567890", header="Header", footer="Footer"
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["interactive"]["header"]["text"] == "Header"
    assert payload["interactive"]["footer"]["text"] == "Footer"


def test_send_list_message(whatsapp_tools):
    sections = [
        {
            "title": "Options",
            "rows": [
                {"id": "row_1", "title": "Option A", "description": "First option"},
                {"id": "row_2", "title": "Option B"},
            ],
        }
    ]
    result = whatsapp_tools.send_list_message(
        body_text="Choose one",
        button_text="View",
        sections=sections,
        recipient="+1234567890",
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["interactive"]["type"] == "list"
    assert payload["interactive"]["action"]["button"] == "View"


def test_send_image_by_url(whatsapp_tools):
    result = whatsapp_tools.send_image(
        image_url="https://example.com/img.png", recipient="+1234567890", caption="A photo"
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["image"]["link"] == "https://example.com/img.png"
    assert payload["image"]["caption"] == "A photo"


def test_send_image_by_media_id(whatsapp_tools):
    result = whatsapp_tools.send_image(media_id="media_123", recipient="+1234567890")
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["image"]["id"] == "media_123"
    assert "link" not in payload["image"]


def test_send_image_no_source(whatsapp_tools):
    result = whatsapp_tools.send_image(recipient="+1234567890")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "image_url or media_id" in parsed["error"]


def test_send_document(whatsapp_tools):
    result = whatsapp_tools.send_document(
        document_url="https://example.com/doc.pdf",
        filename="report.pdf",
        caption="Monthly report",
        recipient="+1234567890",
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["document"]["link"] == "https://example.com/doc.pdf"
    assert payload["document"]["filename"] == "report.pdf"


def test_send_document_no_source(whatsapp_tools):
    result = whatsapp_tools.send_document(recipient="+1234567890")
    parsed = json.loads(result)
    assert "error" in parsed


def test_send_location(whatsapp_tools):
    result = whatsapp_tools.send_location(
        latitude="37.7749",
        longitude="-122.4194",
        name="San Francisco",
        address="SF, CA",
        recipient="+1234567890",
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["type"] == "location"
    assert payload["location"]["latitude"] == "37.7749"
    assert payload["location"]["name"] == "San Francisco"


def test_send_reaction(whatsapp_tools):
    result = whatsapp_tools.send_reaction(message_id="wamid.abc123", emoji="\U0001f44d", recipient="+1234567890")
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["type"] == "reaction"
    assert payload["reaction"]["message_id"] == "wamid.abc123"
    assert payload["reaction"]["emoji"] == "\U0001f44d"


def test_mark_as_read(whatsapp_tools):
    whatsapp_tools._mock_httpx.post.return_value.json.return_value = {"success": True}
    result = whatsapp_tools.mark_as_read(message_id="wamid.abc123")
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["status"] == "read"
    assert payload["message_id"] == "wamid.abc123"
