"""Unit tests for GoogleSlidesTools."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from google.oauth2.credentials import Credentials

from agno.tools.google.slides import GoogleSlidesTools


@pytest.fixture
def mock_slides_service():
    service = MagicMock()
    presentations = service.presentations.return_value

    presentations.create.return_value.execute.return_value = {
        "presentationId": "test-presentation-id",
        "title": "Test Presentation",
    }
    presentations.get.return_value.execute.return_value = {
        "presentationId": "test-presentation-id",
        "title": "Test Presentation",
        "slides": [
            {
                "objectId": "slide_1",
                "pageElements": [
                    {
                        "shape": {
                            "text": {
                                "textElements": [
                                    {"textRun": {"content": "Hello World"}},
                                    {"textRun": {"content": "  "}},
                                ]
                            }
                        }
                    }
                ],
            }
        ],
    }
    presentations.batchUpdate.return_value.execute.return_value = {
        "presentationId": "test-presentation-id",
        "replies": [{}],
    }

    pages = presentations.pages.return_value
    pages.getThumbnail.return_value.execute.return_value = {"contentUrl": "https://example.com/thumbnail.png"}
    pages.get.return_value.execute.return_value = {
        "objectId": "slide_1",
        "pageElements": [
            {
                "objectId": "placeholder_title",
                "shape": {
                    "placeholder": {"type": "TITLE"},
                    "text": {"textElements": [{"textRun": {"content": "Slide Text"}}]},
                },
            },
            {
                "objectId": "placeholder_subtitle",
                "shape": {
                    "placeholder": {"type": "SUBTITLE"},
                    "text": {"textElements": [{"textRun": {"content": "Subtitle Text"}}]},
                },
            },
            {
                "objectId": "placeholder_body_1",
                "shape": {
                    "placeholder": {"type": "BODY"},
                    "text": {"textElements": [{"textRun": {"content": "Body Text 1"}}]},
                },
            },
            {
                "objectId": "placeholder_body_2",
                "shape": {
                    "placeholder": {"type": "BODY"},
                    "text": {"textElements": [{"textRun": {"content": "Body Text 2"}}]},
                },
            },
        ],
    }
    return service


@pytest.fixture
def mock_drive_service():
    service = MagicMock()
    files = service.files.return_value
    files.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "test-presentation-id",
                "name": "Test Presentation",
                "createdTime": "2025-01-01T00:00:00Z",
                "modifiedTime": "2025-09-17T12:00:00Z",
            }
        ]
    }
    files.delete.return_value.execute.return_value = {}
    return service


@pytest.fixture
def mock_credentials():
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = True
    mock_creds.expired = False
    return mock_creds


@pytest.fixture
def tools(mock_credentials, mock_slides_service, mock_drive_service):
    with (
        patch("agno.tools.google.slides.build"),
        patch("agno.tools.google.slides.authenticate", lambda func: func),
    ):
        toolkit = GoogleSlidesTools(creds=mock_credentials)
        toolkit.slides_service = mock_slides_service
        toolkit.drive_service = mock_drive_service
        toolkit.service = mock_slides_service
        return toolkit


def ok(response: str) -> dict:
    """Parse a JSON response and assert it has no 'error' key."""
    data = json.loads(response)
    assert "error" not in data, f"Unexpected error: {data.get('error')}"
    return data


def err(response: str) -> str:
    """Parse a JSON response, assert it has an 'error' key, return the message."""
    data = json.loads(response)
    assert "error" in data, f"Expected error but got: {data}"
    return data["error"]


class TestInitialization:
    def test_default_scopes(self):
        with patch("agno.tools.google.slides.authenticate", lambda func: func):
            toolkit = GoogleSlidesTools()
            assert "https://www.googleapis.com/auth/drive.file" in toolkit.scopes
            assert "https://www.googleapis.com/auth/presentations" in toolkit.scopes
            assert "https://www.googleapis.com/auth/drive" not in toolkit.scopes

    def test_to_emu_helper(self):
        with patch("agno.tools.google.slides.authenticate", lambda func: func):
            toolkit = GoogleSlidesTools()
            assert toolkit._to_emu(1, "inch") == 914400
            assert toolkit._to_emu(72, "point") == 914400
            assert toolkit._to_emu(100, "raw") == 100

    def test_to_emu_zero(self):
        """_to_emu(0, ...) must always return 0 regardless of unit."""
        with patch("agno.tools.google.slides.authenticate", lambda func: func):
            toolkit = GoogleSlidesTools()
            assert toolkit._to_emu(0, "inch") == 0
            assert toolkit._to_emu(0, "point") == 0
            assert toolkit._to_emu(0, "raw") == 0


class TestCreatePresentation:
    def test_success(self, tools):
        data = ok(tools.create_presentation("My Deck"))
        assert data["presentation_id"] == "test-presentation-id"
        assert data["title"] == "My Deck"
        assert "docs.google.com/presentation" in data["url"]

    def test_empty_title(self, tools):
        assert "empty" in err(tools.create_presentation(""))

    def test_whitespace_title(self, tools):
        assert "empty" in err(tools.create_presentation("   "))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.create.return_value.execute.side_effect = Exception(
            "quota exceeded"
        )
        assert "quota exceeded" in err(tools.create_presentation("Valid Title"))


class TestGetPresentation:
    def test_success(self, tools):
        data = ok(tools.get_presentation("test-presentation-id"))
        assert data["presentationId"] == "test-presentation-id"
        assert len(data.get("slides", [])) == 1

    def test_with_fields(self, tools):
        tools.get_presentation("test-presentation-id", fields="title,slides")
        call_kwargs = tools.slides_service.presentations.return_value.get.call_args
        assert call_kwargs.kwargs.get("fields") == "title,slides"

    def test_without_fields(self, tools):
        tools.get_presentation("test-presentation-id")
        call_kwargs = tools.slides_service.presentations.return_value.get.call_args
        assert call_kwargs.kwargs.get("fields") is None

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.get_presentation(""))

    def test_whitespace_presentation_id(self, tools):
        assert "empty" in err(tools.get_presentation("   "))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.get.return_value.execute.side_effect = Exception("not found")
        assert "not found" in err(tools.get_presentation("bad-id"))


class TestListPresentations:
    def test_success(self, tools):
        data = ok(tools.list_presentations())
        assert "presentations" in data
        assert isinstance(data["presentations"], list)
        assert data["presentations"][0]["name"] == "Test Presentation"

    def test_custom_page_size(self, tools):
        tools.list_presentations(page_size=5)
        call_kwargs = tools.drive_service.files.return_value.list.call_args
        assert call_kwargs.kwargs["pageSize"] == 5

    def test_zero_page_size(self, tools):
        assert "positive" in err(tools.list_presentations(page_size=0))

    def test_negative_page_size(self, tools):
        assert "positive" in err(tools.list_presentations(page_size=-1))

    def test_api_error(self, tools):
        tools.drive_service.files.return_value.list.return_value.execute.side_effect = Exception("drive error")
        assert "drive error" in err(tools.list_presentations())

    def test_pagination(self, tools):
        tools.list_presentations(page_token="test-token")
        call_kwargs = tools.drive_service.files.return_value.list.call_args
        assert call_kwargs.kwargs["pageToken"] == "test-token"


class TestDeletePresentation:
    def test_success(self, tools):
        data = ok(tools.delete_presentation("pres-id"))
        assert data["deleted"] == "pres-id"

    def test_empty_id(self, tools):
        assert "empty" in err(tools.delete_presentation(""))

    def test_whitespace_id(self, tools):
        assert "empty" in err(tools.delete_presentation("   "))

    def test_api_error(self, tools):
        tools.drive_service.files.return_value.delete.return_value.execute.side_effect = Exception("forbidden")
        assert "forbidden" in err(tools.delete_presentation("pres-id"))


class TestAddSlide:
    def test_success_default_layout(self, tools):
        data = ok(tools.add_slide("pres-id", title="Hello", body="World"))
        assert data["title"] is None  # Marked inserted
        assert data["body"] is None  # Marked inserted
        assert "slide_id" in data

    def test_success_complex_layout(self, tools):
        data = ok(
            tools.add_slide("pres-id", layout="TITLE_AND_TWO_COLUMNS", title="Two Cols", body="Left", body_2="Right")
        )
        assert data["title"] is None
        assert data["body"] is None
        assert "slide_id" in data
        # Verify batchUpdate was called for both bodies
        calls = tools.slides_service.presentations.return_value.batchUpdate.call_args_list
        # First call is createSlide, second is text insertions
        text_insertion_call = calls[1]
        requests = text_insertion_call.kwargs["body"]["requests"]
        inserted_texts = [r["insertText"]["text"] for r in requests if "insertText" in r]
        assert "Left" in inserted_texts
        assert "Right" in inserted_texts

    def test_subtitle_support(self, tools):
        data = ok(tools.add_slide("pres-id", layout="TITLE", title="H1", subtitle="H2"))
        assert data["title"] is None
        assert data["subtitle"] is None

    def test_blank_layout(self, tools):
        data = ok(tools.add_slide("pres-id", layout="BLANK"))
        assert data["layout"] == "BLANK"

    @pytest.mark.parametrize(
        "layout",
        [
            "TITLE",
            "TITLE_AND_BODY",
            "TITLE_ONLY",
            "SECTION_HEADER",
            "SECTION_TITLE_AND_DESCRIPTION",
            "ONE_COLUMN_TEXT",
            "MAIN_POINT",
            "BIG_NUMBER",
            "CAPTION_ONLY",
            "TITLE_AND_TWO_COLUMNS",
        ],
    )
    def test_all_valid_layouts(self, tools, layout):
        data = ok(tools.add_slide("pres-id", layout=layout))
        assert data["layout"] == layout

    def test_invalid_layout(self, tools):
        assert "Invalid layout" in err(tools.add_slide("pres-id", layout="SUPER_FANCY"))

    def test_negative_insertion_index(self, tools):
        assert ">= 0" in err(tools.add_slide("pres-id", insertion_index=-1))

    def test_zero_insertion_index_allowed(self, tools):
        data = ok(tools.add_slide("pres-id", insertion_index=0))
        assert "slide_id" in data

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.add_slide(""))

    def test_no_title_or_body(self, tools):
        data = ok(tools.add_slide("pres-id"))
        assert data["title"] is None
        assert data["body"] is None

    def test_caption_only_layout(self, tools):
        # CAPTION_ONLY usually only has BODY. title=None should still mark as inserted if mapped
        data = ok(tools.add_slide("pres-id", layout="CAPTION_ONLY", body="Caption text"))
        assert data["layout"] == "CAPTION_ONLY"

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "slide error"
        )
        assert "slide error" in err(tools.add_slide("pres-id", layout="BLANK"))

    def test_text_insertion_partial_failure(self, tools):
        # First call success (createSlide), second call fails (text insertion)
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = [
            {"presentationId": "p1"},  # createSlide
            Exception("Insertion fail"),  # text insertion
        ]
        data = ok(tools.add_slide("pres-id", title="Title", body="Body"))
        assert "warnings" in data
        assert "Insertion fail" in data["warnings"][0]
        # Text fields should still contain the content that was NOT successfully cleared/inserted
        assert data["title"] == "Title"
        assert data["body"] == "Body"


class TestDeleteSlide:
    def test_success(self, tools):
        data = ok(tools.delete_slide("pres-id", "slide-1"))
        assert data["deleted_slide"] == "slide-1"

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.delete_slide("", "slide-1"))

    def test_empty_slide_id(self, tools):
        assert "empty" in err(tools.delete_slide("pres-id", ""))

    def test_whitespace_slide_id(self, tools):
        assert "empty" in err(tools.delete_slide("pres-id", "   "))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "not found"
        )
        assert "not found" in err(tools.delete_slide("pres-id", "slide-1"))


class TestDuplicateSlide:
    def test_success(self, tools):
        data = ok(tools.duplicate_slide("pres-id", "slide-1"))
        assert "presentationId" in data

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.duplicate_slide("", "slide-1"))

    def test_empty_slide_id(self, tools):
        assert "empty" in err(tools.duplicate_slide("pres-id", ""))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "dup error"
        )
        assert "dup error" in err(tools.duplicate_slide("pres-id", "slide-1"))


class TestMoveSlides:
    def test_success(self, tools):
        data = ok(tools.move_slides("pres-id", ["slide-1", "slide-2"], insertion_index=0))
        assert data["moved"] == ["slide-1", "slide-2"]
        assert data["to_index"] == 0

    def test_empty_slide_ids_list(self, tools):
        assert "empty" in err(tools.move_slides("pres-id", [], insertion_index=1))

    def test_negative_insertion_index(self, tools):
        assert ">= 0" in err(tools.move_slides("pres-id", ["slide-1"], insertion_index=-1))

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.move_slides("", ["slide-1"], insertion_index=0))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "move error"
        )
        assert "move error" in err(tools.move_slides("pres-id", ["slide-1"], insertion_index=0))


class TestAddTextBox:
    def test_success(self, tools):
        data = ok(tools.add_text_box("pres-id", "slide-1", "Hello!"))
        assert "text_box_id" in data
        assert data["slide_id"] == "slide-1"

    def test_custom_dimensions(self, tools):
        # 2x2 inches = 1828800 EMUs
        data = ok(tools.add_text_box("pres-id", "slide-1", "Hi", x=2, y=2, width=4, height=1.5))
        assert "text_box_id" in data
        last_call = tools.slides_service.presentations.return_value.batchUpdate.call_args
        req = last_call.kwargs["body"]["requests"][0]["createShape"]
        assert req["elementProperties"]["size"]["width"]["magnitude"] == 4 * 914400
        assert req["elementProperties"]["transform"]["translateX"] == 2 * 914400

    def test_empty_text(self, tools):
        assert "empty" in err(tools.add_text_box("pres-id", "slide-1", ""))

    def test_whitespace_text(self, tools):
        assert "empty" in err(tools.add_text_box("pres-id", "slide-1", "   "))

    def test_zero_width(self, tools):
        assert "positive" in err(tools.add_text_box("pres-id", "slide-1", "Hi", width=0))

    def test_negative_width(self, tools):
        assert "positive" in err(tools.add_text_box("pres-id", "slide-1", "Hi", width=-1))

    def test_zero_height(self, tools):
        assert "positive" in err(tools.add_text_box("pres-id", "slide-1", "Hi", height=0))

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.add_text_box("", "slide-1", "Hi"))

    def test_empty_slide_id(self, tools):
        assert "empty" in err(tools.add_text_box("pres-id", "", "Hi"))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "textbox error"
        )
        assert "textbox error" in err(tools.add_text_box("pres-id", "slide-1", "Hi"))


class TestAddTable:
    def test_success_no_content(self, tools):
        data = ok(tools.add_table("pres-id", "slide-1", rows=3, columns=2))
        assert "table_id" in data
        assert data["rows"] == 3
        assert data["columns"] == 2

    def test_success_with_content(self, tools):
        content = [["H1", "H2"], ["R1C1", "R1C2"]]
        data = ok(tools.add_table("pres-id", "slide-1", rows=2, columns=2, content=content))
        assert data["rows"] == 2

    def test_zero_rows(self, tools):
        assert "positive" in err(tools.add_table("pres-id", "slide-1", rows=0, columns=2))

    def test_negative_rows(self, tools):
        assert "positive" in err(tools.add_table("pres-id", "slide-1", rows=-1, columns=2))

    def test_zero_columns(self, tools):
        assert "positive" in err(tools.add_table("pres-id", "slide-1", rows=2, columns=0))

    def test_content_too_many_rows(self, tools):
        content = [["A"], ["B"], ["C"]]  # 3 rows but table only has 2
        assert "exceed" in err(tools.add_table("pres-id", "slide-1", rows=2, columns=1, content=content))

    def test_content_too_many_columns(self, tools):
        content = [["A", "B", "C"]]  # 3 cols but table only has 2
        assert "exceed" in err(tools.add_table("pres-id", "slide-1", rows=1, columns=2, content=content))

    def test_content_empty_cells_skipped(self, tools):
        """Empty-string cells are silently skipped (the `if cell:` guard in add_table).
        The API call must still succeed and no insertText request is emitted for them."""
        content = [["", "B"], ["C", ""]]  # two empty cells out of four
        data = ok(tools.add_table("pres-id", "slide-1", rows=2, columns=2, content=content))
        assert data["rows"] == 2
        assert data["columns"] == 2
        # Verify only 2 insertText requests were emitted (one per non-empty cell),
        # plus the initial createTable request = 3 total.
        last_call = tools.slides_service.presentations.return_value.batchUpdate.call_args
        all_requests = last_call.kwargs["body"]["requests"]
        insert_text_reqs = [r for r in all_requests if "insertText" in r]
        assert len(insert_text_reqs) == 2
        inserted_texts = {r["insertText"]["text"] for r in insert_text_reqs}
        assert inserted_texts == {"B", "C"}

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.add_table("", "slide-1", rows=2, columns=2))

    def test_empty_slide_id(self, tools):
        assert "empty" in err(tools.add_table("pres-id", "", rows=2, columns=2))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "table error"
        )
        assert "table error" in err(tools.add_table("pres-id", "slide-1", rows=2, columns=2))


class TestSetBackgroundImage:
    def test_success(self, tools):
        data = ok(tools.set_background_image("pres-id", "slide-1", "https://example.com/bg.png"))
        assert data["background_set"] is True
        assert data["slide_id"] == "slide-1"

    def test_empty_image_url(self, tools):
        assert "empty" in err(tools.set_background_image("pres-id", "slide-1", ""))

    def test_whitespace_image_url(self, tools):
        assert "empty" in err(tools.set_background_image("pres-id", "slide-1", "   "))

    def test_ftp_url_rejected(self, tools):
        """SSRF protection: non-http/https schemes must be rejected."""
        assert "valid http" in err(tools.set_background_image("pres-id", "slide-1", "ftp://evil.com/img.png"))

    def test_no_scheme_rejected(self, tools):
        """SSRF protection: URLs without a scheme must be rejected."""
        assert "valid http" in err(tools.set_background_image("pres-id", "slide-1", "not-a-url"))

    def test_missing_netloc_rejected(self, tools):
        """SSRF protection: a scheme with no host must be rejected."""
        assert "valid http" in err(tools.set_background_image("pres-id", "slide-1", "https://"))

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.set_background_image("", "slide-1", "https://x.com/img.png"))

    def test_empty_slide_id(self, tools):
        assert "empty" in err(tools.set_background_image("pres-id", "", "https://x.com/img.png"))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "bg error"
        )
        assert "bg error" in err(tools.set_background_image("pres-id", "slide-1", "https://x.com/img.png"))


class TestReadAllText:
    def test_success(self, tools):
        # Test deep extraction
        tools.slides_service.presentations.return_value.get.return_value.execute.return_value = {
            "presentationId": "pres-id",
            "slides": [
                {
                    "objectId": "slide_1",
                    "pageElements": [
                        {"shape": {"text": {"textElements": [{"textRun": {"content": "Shape Text\n"}}]}}},
                        {
                            "table": {
                                "tableRows": [
                                    {
                                        "tableCells": [
                                            {"text": {"textElements": [{"textRun": {"content": "Table Cell\n"}}]}}
                                        ]
                                    }
                                ]
                            }
                        },
                        {
                            "elementGroup": {
                                "children": [
                                    {"shape": {"text": {"textElements": [{"textRun": {"content": "Grouped Text\n"}}]}}}
                                ]
                            }
                        },
                    ],
                }
            ],
        }
        data = ok(tools.read_all_text("pres-id"))
        assert "slide_1" in data
        assert "Shape Text" in data["slide_1"]
        assert "Table Cell" in data["slide_1"]
        assert "Grouped Text" in data["slide_1"]

    def test_whitespace_filtered_out(self, tools):
        data = ok(tools.read_all_text("pres-id"))
        # The fixture has a whitespace-only textRun; it should not appear
        for text in data["slide_1"]:
            assert text.strip() != ""

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.read_all_text(""))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.get.return_value.execute.side_effect = Exception("read error")
        assert "read error" in err(tools.read_all_text("pres-id"))

    def test_no_slides(self, tools):
        tools.slides_service.presentations.return_value.get.return_value.execute.return_value = {
            "presentationId": "pres-id",
            "slides": [],
        }
        data = ok(tools.read_all_text("pres-id"))
        assert data == {}

    def test_autotext_extracted(self, tools):
        """autoText elements (e.g. slide-numbers) must be extracted by _extract_text_recursive."""
        tools.slides_service.presentations.return_value.get.return_value.execute.return_value = {
            "presentationId": "pres-id",
            "slides": [
                {
                    "objectId": "slide_auto",
                    "pageElements": [
                        {"shape": {"text": {"textElements": [{"autoText": {"content": "Slide 1 of 5"}}]}}}
                    ],
                }
            ],
        }
        data = ok(tools.read_all_text("pres-id"))
        assert "Slide 1 of 5" in data["slide_auto"]


class TestGetThumbnailUrl:
    def test_success(self, tools):
        data = ok(tools.get_slide_thumbnail("pres-id", "slide-1"))
        assert data["thumbnail_url"] == "https://example.com/thumbnail.png"

    def test_missing_content_url(self, tools):
        tools.slides_service.presentations.return_value.pages.return_value.getThumbnail.return_value.execute.return_value = {}
        assert "No thumbnail" in err(tools.get_slide_thumbnail("pres-id", "slide-1"))

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.get_slide_thumbnail("", "slide-1"))

    def test_empty_slide_id(self, tools):
        assert "empty" in err(tools.get_slide_thumbnail("pres-id", ""))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.pages.return_value.getThumbnail.return_value.execute.side_effect = Exception(
            "thumb error"
        )
        assert "thumb error" in err(tools.get_slide_thumbnail("pres-id", "slide-1"))


class TestGetPresentationMetadata:
    def test_success(self, tools):
        tools.slides_service.presentations.return_value.get.return_value.execute.return_value = {
            "presentationId": "pres-id",
            "title": "My Deck",
            "pageSize": {
                "width": {"magnitude": 9144000, "unit": "EMU"},
                "height": {"magnitude": 5143500, "unit": "EMU"},
            },
            "slides": [{"objectId": "s1"}, {"objectId": "s2"}],
        }
        data = ok(tools.get_presentation_metadata("pres-id"))
        assert data["slide_count"] == 2
        assert data["slides"][0]["slide_id"] == "s1"
        assert data["slides"][1]["slide_id"] == "s2"
        assert data["title"] == "My Deck"
        assert data["page_width_inches"] == 10.0

    def test_no_slides(self, tools):
        tools.slides_service.presentations.return_value.get.return_value.execute.return_value = {
            "presentationId": "pres-id",
            "title": "Empty",
            "pageSize": {
                "width": {"magnitude": 9144000, "unit": "EMU"},
                "height": {"magnitude": 5143500, "unit": "EMU"},
            },
            "slides": [],
        }
        data = ok(tools.get_presentation_metadata("pres-id"))
        assert data["slide_count"] == 0
        assert data["slides"] == []

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.get_presentation_metadata(""))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.get.return_value.execute.side_effect = Exception("meta error")
        assert "meta error" in err(tools.get_presentation_metadata("pres-id"))


class TestGetPage:
    def test_success(self, tools):
        data = ok(tools.get_page("pres-id", "slide-1"))
        assert data["objectId"] == "slide_1"

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.get_page("", "slide-1"))

    def test_empty_page_object_id(self, tools):
        assert "empty" in err(tools.get_page("pres-id", ""))

    def test_whitespace_page_object_id(self, tools):
        assert "empty" in err(tools.get_page("pres-id", "   "))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.pages.return_value.get.return_value.execute.side_effect = (
            Exception("page error")
        )
        assert "page error" in err(tools.get_page("pres-id", "slide-1"))


class TestGetSlideText:
    def test_success(self, tools):
        # Test deep extraction
        tools.slides_service.presentations.return_value.pages.return_value.get.return_value.execute.return_value = {
            "objectId": "slide-1",
            "pageElements": [
                {"shape": {"text": {"textElements": [{"textRun": {"content": "Shape Text\n"}}]}}},
                {
                    "table": {
                        "tableRows": [
                            {"tableCells": [{"text": {"textElements": [{"textRun": {"content": "Table Cell\n"}}]}}]}
                        ]
                    }
                },
                {"wordArt": {"renderedText": "Word Art Content"}},
            ],
        }
        data = ok(tools.get_slide_text("pres-id", "slide-1"))
        assert data["slide_id"] == "slide-1"
        assert "Shape Text" in data["text"]
        assert "Table Cell" in data["text"]
        assert "Word Art Content" in data["text"]

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.get_slide_text("", "slide-1"))

    def test_empty_page_object_id(self, tools):
        assert "empty" in err(tools.get_slide_text("pres-id", ""))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.pages.return_value.get.return_value.execute.side_effect = (
            Exception("text error")
        )
        assert "text error" in err(tools.get_slide_text("pres-id", "slide-1"))

    def test_no_text_elements(self, tools):
        tools.slides_service.presentations.return_value.pages.return_value.get.return_value.execute.return_value = {
            "objectId": "slide-1",
            "pageElements": [],
        }
        data = ok(tools.get_slide_text("pres-id", "slide-1"))
        assert data["text"] == []


class TestInsertYoutubeVideo:
    def test_success(self, tools):
        data = ok(tools.insert_youtube_video("pres-id", "slide-1", "dQw4w9WgXcQ", x=1, y=1, width=4, height=3))
        assert "video_object_id" in data
        assert data["youtube_video_id"] == "dQw4w9WgXcQ"
        assert data["slide_id"] == "slide-1"
        # Verify EMU conversion
        last_call = tools.slides_service.presentations.return_value.batchUpdate.call_args
        req = last_call.kwargs["body"]["requests"][0]["createVideo"]
        assert req["elementProperties"]["size"]["width"]["magnitude"] == 4 * 914400
        assert req["elementProperties"]["transform"]["translateX"] == 1 * 914400

    def test_empty_video_id(self, tools):
        assert "empty" in err(tools.insert_youtube_video("pres-id", "slide-1", ""))

    def test_whitespace_video_id(self, tools):
        assert "empty" in err(tools.insert_youtube_video("pres-id", "slide-1", "   "))

    def test_zero_width(self, tools):
        assert "positive" in err(tools.insert_youtube_video("pres-id", "slide-1", "abc", width=0))

    def test_negative_height(self, tools):
        assert "positive" in err(tools.insert_youtube_video("pres-id", "slide-1", "abc", height=-1))

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.insert_youtube_video("", "slide-1", "abc"))

    def test_empty_slide_id(self, tools):
        assert "empty" in err(tools.insert_youtube_video("pres-id", "", "abc"))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "yt error"
        )
        assert "yt error" in err(tools.insert_youtube_video("pres-id", "slide-1", "abc"))


class TestInsertDriveVideo:
    def test_success(self, tools):
        data = ok(tools.insert_drive_video("pres-id", "slide-1", "drive-file-id", x=2, y=2, width=6, height=4))
        assert "video_object_id" in data
        assert data["drive_file_id"] == "drive-file-id"
        assert data["slide_id"] == "slide-1"
        # Verify EMU conversion
        last_call = tools.slides_service.presentations.return_value.batchUpdate.call_args
        req = last_call.kwargs["body"]["requests"][0]["createVideo"]
        assert req["elementProperties"]["size"]["width"]["magnitude"] == 6 * 914400
        assert req["elementProperties"]["transform"]["translateX"] == 2 * 914400

    def test_empty_file_id(self, tools):
        assert "empty" in err(tools.insert_drive_video("pres-id", "slide-1", ""))

    def test_whitespace_file_id(self, tools):
        assert "empty" in err(tools.insert_drive_video("pres-id", "slide-1", "   "))

    def test_zero_width(self, tools):
        assert "positive" in err(tools.insert_drive_video("pres-id", "slide-1", "file-id", width=0))

    def test_negative_height(self, tools):
        assert "positive" in err(tools.insert_drive_video("pres-id", "slide-1", "file-id", height=-1))

    def test_empty_presentation_id(self, tools):
        assert "empty" in err(tools.insert_drive_video("", "slide-1", "file-id"))

    def test_empty_slide_id(self, tools):
        assert "empty" in err(tools.insert_drive_video("pres-id", "", "file-id"))

    def test_api_error(self, tools):
        tools.slides_service.presentations.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "drive video error"
        )
        assert "drive video error" in err(tools.insert_drive_video("pres-id", "slide-1", "file-id"))


class TestIdUniqueness:
    def test_slide_ids_are_unique(self, tools):
        """Each add_slide call should produce a different slideId."""
        ids = set()
        for _ in range(10):
            data = ok(tools.add_slide("pres-id", layout="BLANK"))
            ids.add(data["slide_id"])
        assert len(ids) == 10

    def test_textbox_ids_are_unique(self, tools):
        ids = set()
        for _ in range(10):
            data = ok(tools.add_text_box("pres-id", "slide-1", "text"))
            ids.add(data["text_box_id"])
        assert len(ids) == 10

    def test_table_ids_are_unique(self, tools):
        ids = set()
        for _ in range(10):
            data = ok(tools.add_table("pres-id", "slide-1", rows=2, columns=2))
            ids.add(data["table_id"])
        assert len(ids) == 10


class TestToolFiltering:
    def test_include_tools(self):
        with patch("agno.tools.google.slides.authenticate", lambda func: func):
            toolkit = GoogleSlidesTools(include_tools=["create_presentation", "get_presentation"])
        assert len(toolkit.functions) == 2
        assert "create_presentation" in toolkit.functions
        assert "get_presentation" in toolkit.functions
        assert "delete_presentation" not in toolkit.functions

    def test_exclude_tools(self):
        with patch("agno.tools.google.slides.authenticate", lambda func: func):
            toolkit = GoogleSlidesTools(delete_presentation=True, exclude_tools=["delete_presentation", "add_slide"])
        assert "delete_presentation" not in toolkit.functions
        assert "add_slide" not in toolkit.functions
        assert "create_presentation" in toolkit.functions

    def test_all_tools_registered_by_default(self):
        with patch("agno.tools.google.slides.authenticate", lambda func: func):
            toolkit = GoogleSlidesTools()
        expected = {
            "create_presentation",
            "get_presentation",
            "list_presentations",
            # "delete_presentation",
            "add_slide",
            # "delete_slide",
            "duplicate_slide",
            "move_slides",
            "add_text_box",
            "add_table",
            "set_background_image",
            "read_all_text",
            "get_slide_thumbnail",
            "get_presentation_metadata",
            "get_page",
            "get_slide_text",
            "insert_youtube_video",
            "insert_drive_video",
        }
        assert expected == set(toolkit.functions.keys())

    def test_include_and_exclude_combined(self):
        """Both filters are applied independently (toolkit.py Toolkit.register lines 180-183):
          1. include_tools narrows the candidate set (skip if not in include list).
          2. exclude_tools then strips from that narrowed set (skip if in exclude list).
        So include=[A,B,C] + exclude=[C]  →  {A, B} are registered.
        This is verified directly against Agno's Toolkit source code."""
        with patch("agno.tools.google.slides.authenticate", lambda func: func):
            toolkit = GoogleSlidesTools(
                delete_presentation=True,
                include_tools=["create_presentation", "get_presentation", "delete_presentation"],
                exclude_tools=["delete_presentation"],
            )
        # delete_presentation is excluded; only the remaining two should be present.
        assert "delete_presentation" not in toolkit.functions
        assert "create_presentation" in toolkit.functions
        assert "get_presentation" in toolkit.functions
        assert len(toolkit.functions) == 2
