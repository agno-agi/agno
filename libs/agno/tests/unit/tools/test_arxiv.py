import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agno.tools.arxiv import ArxivTools


def test_read_arxiv_papers_downloads_pdf_from_url(tmp_path):
    result = SimpleNamespace(
        title="Test Paper",
        entry_id="https://arxiv.org/abs/1234.5678v1",
        authors=[SimpleNamespace(name="Ada Lovelace")],
        primary_category="cs.AI",
        categories=["cs.AI"],
        published=None,
        pdf_url="https://arxiv.org/pdf/1234.5678v1",
        links=[SimpleNamespace(href="https://arxiv.org/pdf/1234.5678v1")],
        summary="A test summary.",
        comment=None,
        get_short_id=Mock(return_value="1234.5678v1"),
    )
    mock_response = Mock(content=b"%PDF-1.4 test")
    mock_response.raise_for_status = Mock()
    mock_page = Mock()
    mock_page.extract_text.return_value = "page text"

    tools = ArxivTools(download_dir=tmp_path)
    tools.client = Mock()
    tools.client.results.return_value = [result]

    with (
        patch("agno.tools.arxiv.arxiv.Search"),
        patch("agno.tools.arxiv.httpx.get", return_value=mock_response) as get,
        patch("agno.tools.arxiv.PdfReader") as pdf_reader,
    ):
        pdf_reader.return_value.pages = [mock_page]

        output = json.loads(tools.read_arxiv_papers(id_list=["1234.5678v1"], pages_to_read=1))

    get.assert_called_once_with("https://arxiv.org/pdf/1234.5678v1", follow_redirects=True)
    mock_response.raise_for_status.assert_called_once()
    assert tmp_path.joinpath("1234.5678v1.pdf").read_bytes() == b"%PDF-1.4 test"
    assert output[0]["content"] == [{"page": 1, "text": "page text"}]
