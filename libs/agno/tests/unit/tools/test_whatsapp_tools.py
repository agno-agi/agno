import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.whatsapp import ListRow, ListSection, ReplyButton, WhatsAppTools

ENV = {
    "WHATSAPP_ACCESS_TOKEN": "test-token",
    "WHATSAPP_PHONE_NUMBER_ID": "123456",
}


@pytest.fixture
def whatsapp_tools():
    with patch.dict("os.environ", ENV):
        with patch("agno.tools.whatsapp.httpx") as mock_httpx:
            mock_response = Mock()
            mock_response.status_code = 200
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
        assert len(tools.functions) == 8


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
    env = {**ENV, "WHATSAPP_RECIPIENT_WAID": ""}
    with patch.dict("os.environ", env, clear=False):
        with patch("agno.tools.whatsapp.httpx"):
            tools = WhatsAppTools()
            result = tools.send_text_message(text="Hello")
            parsed = json.loads(result)
            assert "error" in parsed
            assert "recipient" in parsed["error"].lower()


def test_send_text_message_error(whatsapp_tools):
    whatsapp_tools._mock_httpx.post.side_effect = Exception("API error")
    with pytest.raises(Exception, match="API error"):
        whatsapp_tools.send_text_message(text="Hello", recipient="+1234567890")


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


# === Interactive Tools ===


def test_send_reply_buttons(whatsapp_tools):
    buttons = [
        ReplyButton(id="btn_yes", title="Yes"),
        ReplyButton(id="btn_no", title="No"),
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
    buttons = [ReplyButton(id=f"btn_{i}", title=f"Btn {i}") for i in range(4)]
    result = whatsapp_tools.send_reply_buttons(body_text="Too many", buttons=buttons, recipient="+1234567890")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "1-3" in parsed["error"]


def test_send_reply_buttons_with_header_footer(whatsapp_tools):
    buttons = [ReplyButton(id="btn_1", title="OK")]
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
        ListSection(
            title="Options",
            rows=[
                ListRow(id="row_1", title="Option A", description="First option"),
                ListRow(id="row_2", title="Option B"),
            ],
        )
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


# === Edge Cases ===


def test_send_reply_buttons_empty_list(whatsapp_tools):
    result = whatsapp_tools.send_reply_buttons(body_text="Choose", buttons=[], recipient="+1234567890")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "1-3" in parsed["error"]


def test_send_list_message_exceeds_sections(whatsapp_tools):
    sections = [ListSection(title=f"Section {i}", rows=[ListRow(id=f"r_{i}", title=f"Row {i}")]) for i in range(11)]
    result = whatsapp_tools.send_list_message(
        body_text="Too many", button_text="View", sections=sections, recipient="+1234567890"
    )
    parsed = json.loads(result)
    assert "error" in parsed
    assert "10 sections" in parsed["error"]


def test_send_list_message_exceeds_total_rows(whatsapp_tools):
    sections = [
        ListSection(
            title="Sec",
            rows=[ListRow(id=f"r_{i}", title=f"Row {i}") for i in range(11)],
        )
    ]
    result = whatsapp_tools.send_list_message(
        body_text="Too many rows", button_text="View", sections=sections, recipient="+1234567890"
    )
    parsed = json.loads(result)
    assert "error" in parsed
    assert "10 rows" in parsed["error"]


def test_send_document_by_media_id(whatsapp_tools):
    result = whatsapp_tools.send_document(media_id="doc_media_123", filename="report.pdf", recipient="+1234567890")
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["document"]["id"] == "doc_media_123"
    assert "link" not in payload["document"]


def test_send_image_both_url_and_media_id(whatsapp_tools):
    result = whatsapp_tools.send_image(
        image_url="https://example.com/img.png", media_id="media_123", recipient="+1234567890"
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["image"]["id"] == "media_123"
    assert "link" not in payload["image"]


def test_send_location_without_name_and_address(whatsapp_tools):
    result = whatsapp_tools.send_location(latitude="25.7617", longitude="-80.1918", recipient="+1234567890")
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert "name" not in payload["location"]
    assert "address" not in payload["location"]


# === Error Cases ===


def test_send_template_message_error(whatsapp_tools):
    whatsapp_tools._mock_httpx.post.side_effect = Exception("template API error")
    with pytest.raises(Exception, match="template API error"):
        whatsapp_tools.send_template_message(template_name="hello_world", recipient="+1234567890")


def test_send_list_message_error(whatsapp_tools):
    whatsapp_tools._mock_httpx.post.side_effect = Exception("list API error")
    sections = [ListSection(title="Sec", rows=[ListRow(id="r1", title="Row 1")])]
    with pytest.raises(Exception, match="list API error"):
        whatsapp_tools.send_list_message(
            body_text="Body", button_text="View", sections=sections, recipient="+1234567890"
        )


def test_send_image_error(whatsapp_tools):
    whatsapp_tools._mock_httpx.post.side_effect = Exception("image API error")
    with pytest.raises(Exception, match="image API error"):
        whatsapp_tools.send_image(image_url="https://example.com/img.png", recipient="+1234567890")


def test_send_document_error(whatsapp_tools):
    whatsapp_tools._mock_httpx.post.side_effect = Exception("doc API error")
    with pytest.raises(Exception, match="doc API error"):
        whatsapp_tools.send_document(document_url="https://example.com/doc.pdf", recipient="+1234567890")


def test_send_location_error(whatsapp_tools):
    whatsapp_tools._mock_httpx.post.side_effect = Exception("location API error")
    with pytest.raises(Exception, match="location API error"):
        whatsapp_tools.send_location(latitude="0", longitude="0", recipient="+1234567890")


def test_send_reaction_error(whatsapp_tools):
    whatsapp_tools._mock_httpx.post.side_effect = Exception("reaction API error")
    with pytest.raises(Exception, match="reaction API error"):
        whatsapp_tools.send_reaction(message_id="wamid.abc", emoji="\U0001f44d", recipient="+1234567890")


# === Dictionary Input and Coercion Tests ===


def test_send_reply_buttons_with_dict_inputs(whatsapp_tools):
    """Test that send_reply_buttons works when called with raw dicts (as LLMs do)."""
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
    assert payload["interactive"]["action"]["buttons"][0]["reply"]["id"] == "btn_yes"
    assert payload["interactive"]["action"]["buttons"][0]["reply"]["title"] == "Yes"


def test_send_reply_buttons_with_single_dict(whatsapp_tools):
    """Test that send_reply_buttons accepts a single dict button."""
    button = {"id": "btn_confirm", "title": "Confirm"}
    result = whatsapp_tools.send_reply_buttons(body_text="Confirm action?", buttons=button, recipient="+1234567890")
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert len(payload["interactive"]["action"]["buttons"]) == 1


def test_send_reply_buttons_invalid_dict(whatsapp_tools):
    """Test validation when button dict lacks id or title."""
    result = whatsapp_tools.send_reply_buttons(body_text="Test", buttons=[{"id": "only_id"}], recipient="+1234567890")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Each reply button must have non-empty 'id' and 'title'" in parsed["error"]


def test_send_list_message_with_dict_inputs(whatsapp_tools):
    """Test that send_list_message works when called with raw dicts (as LLMs do)."""
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
    assert len(payload["interactive"]["action"]["sections"]) == 1
    assert payload["interactive"]["action"]["sections"][0]["title"] == "Options"
    assert len(payload["interactive"]["action"]["sections"][0]["rows"]) == 2
    assert payload["interactive"]["action"]["sections"][0]["rows"][0]["id"] == "row_1"
    assert payload["interactive"]["action"]["sections"][0]["rows"][0]["description"] == "First option"


def test_send_list_message_with_single_section_dict(whatsapp_tools):
    """Test that send_list_message accepts a single section dict."""
    section = {
        "title": "Single Section",
        "rows": [{"id": "r1", "title": "Row 1"}],
    }
    result = whatsapp_tools.send_list_message(
        body_text="Select", button_text="Open", sections=section, recipient="+1234567890"
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True

    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert len(payload["interactive"]["action"]["sections"]) == 1


def test_send_list_message_invalid_row_dict(whatsapp_tools):
    """Test validation when row dict lacks id or title."""
    sections = [{"title": "Sec", "rows": [{"description": "missing id and title"}]}]
    result = whatsapp_tools.send_list_message(
        body_text="Test", button_text="Open", sections=sections, recipient="+1234567890"
    )
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Each list row must have non-empty 'id' and 'title'" in parsed["error"]


def test_recipient_normalization(whatsapp_tools):
    """Test that recipient phone numbers are stripped of +, spaces, dashes, and parens."""
    whatsapp_tools.send_text_message(text="Hello", recipient="+1 (234) 567-890")
    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["to"] == "1234567890"


def test_recipient_jid_preserved(whatsapp_tools):
    """Test that JIDs containing @ are preserved without phone formatting."""
    whatsapp_tools.send_text_message(text="Hello group", recipient="12036301234567890@g.us")
    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["to"] == "12036301234567890@g.us"


def test_send_reply_buttons_none_or_string(whatsapp_tools):
    """Test that invalid types for buttons return error."""
    result = whatsapp_tools.send_reply_buttons(body_text="Test", buttons=None, recipient="+1234567890")
    assert "WhatsApp requires 1-3 reply buttons" in json.loads(result)["error"]

    result_str = whatsapp_tools.send_reply_buttons(body_text="Test", buttons="invalid", recipient="+1234567890")
    assert "WhatsApp requires 1-3 reply buttons" in json.loads(result_str)["error"]


def test_send_reply_buttons_empty_title_or_id(whatsapp_tools):
    """Test that empty id or title in reply button returns error."""
    result = whatsapp_tools.send_reply_buttons(
        body_text="Test", buttons=[{"id": "btn1", "title": ""}], recipient="+1234567890"
    )
    assert "Each reply button must have non-empty 'id' and 'title'" in json.loads(result)["error"]


def test_send_reply_buttons_truncation(whatsapp_tools):
    """Test that reply button title longer than 20 chars is safely truncated."""
    long_title = "This title is definitely longer than twenty characters"
    result = whatsapp_tools.send_reply_buttons(
        body_text="Test", buttons=[{"id": "btn1", "title": long_title}], recipient="+1234567890"
    )
    assert json.loads(result)["ok"] is True
    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["interactive"]["action"]["buttons"][0]["reply"]["title"] == long_title[:20]


def test_send_list_message_empty_title_or_rows(whatsapp_tools):
    """Test that section with empty title or empty rows returns error."""
    res1 = whatsapp_tools.send_list_message(
        body_text="Test",
        button_text="Open",
        sections=[{"title": "", "rows": [{"id": "1", "title": "A"}]}],
        recipient="+1234567890",
    )
    assert "Each section must have a non-empty 'title'" in json.loads(res1)["error"]

    res2 = whatsapp_tools.send_list_message(
        body_text="Test", button_text="Open", sections=[{"title": "Sec", "rows": []}], recipient="+1234567890"
    )
    assert "must contain a non-empty list of rows" in json.loads(res2)["error"]


def test_send_list_message_row_truncation(whatsapp_tools):
    """Test that row title (>24) and description (>72) are safely truncated."""
    long_title = "A" * 50
    long_desc = "D" * 100
    sections = [{"title": "Sec", "rows": [{"id": "r1", "title": long_title, "description": long_desc}]}]
    result = whatsapp_tools.send_list_message(
        body_text="Test", button_text="Open", sections=sections, recipient="+1234567890"
    )
    assert json.loads(result)["ok"] is True
    call_args = whatsapp_tools._mock_httpx.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    row = payload["interactive"]["action"]["sections"][0]["rows"][0]
    assert row["title"] == "A" * 24
    assert row["description"] == "D" * 72
