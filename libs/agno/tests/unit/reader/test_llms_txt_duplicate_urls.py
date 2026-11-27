"""Duplicate links must not consume the linked-page budget or repeat ingestion."""

import httpx
import pytest

pytest.importorskip("bs4")

from agno.knowledge.reader.llms_txt_reader import LLMsTxtReader  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.parametrize("async_read", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("max_urls", [0, 1, 2, 20])
async def test_duplicate_links_are_fetched_and_ingested_once(monkeypatch, async_read, max_urls):
    index_url = "https://docs.example.com/llms.txt"
    guide_url = "https://docs.example.com/guide"
    api_url = "https://docs.example.com/api"
    extra_url = "https://docs.example.com/extra"
    index = """# Example

## Guides
- [Guide](/guide): Original description
- [Guide again](https://docs.example.com/guide): Duplicate description

## Reference
- [Repeated guide](/guide): Another duplicate
- [API](/api): API description
- [Extra](/extra): Extra description
"""
    requested = []

    def respond(request):
        url = str(request.url)
        requested.append(url)
        return httpx.Response(200, text=index if url == index_url else f"Content of {url}")

    transport = httpx.MockTransport(respond)
    reader = LLMsTxtReader(max_urls=max_urls, chunk=False)
    if async_read:
        client_class = httpx.AsyncClient
        monkeypatch.setattr(
            "agno.knowledge.reader.llms_txt_reader.httpx.AsyncClient",
            lambda **kwargs: client_class(transport=transport, **kwargs),
        )
        documents = await reader.async_read(index_url, name="Example docs")
    else:
        with httpx.Client(transport=transport) as client:
            monkeypatch.setattr(
                "agno.utils.http.httpx.get", lambda url, proxy=None, **kwargs: client.get(url, **kwargs)
            )
            documents = reader.read(index_url, name="Example docs")

    expected_urls = [guide_url, api_url, extra_url][:max_urls]
    assert requested == [index_url, *expected_urls]
    assert documents[0].name == "Example docs"
    assert documents[0].content == "# Example"
    linked = documents[1:]
    assert [doc.meta_data["url"] for doc in linked] == expected_urls
    assert [doc.content for doc in linked] == [f"Content of {url}" for url in expected_urls]
    if linked:
        assert linked[0].name == "Guide"
        assert linked[0].meta_data["section"] == "Guides"
        assert linked[0].meta_data["description"] == "Original description"


def test_index_parser_preserves_repeated_entries():
    """Index tools can still show the same page in each of its original sections."""
    reader = LLMsTxtReader(chunk=False)
    _, entries = reader.parse_llms_txt(
        "## Guides\n- [Guide](/guide)\n## Reference\n- [Guide again](/guide)",
        "https://docs.example.com/llms.txt",
    )
    assert [entry.section for entry in entries] == ["Guides", "Reference"]
    assert [entry.url for entry in entries] == ["https://docs.example.com/guide"] * 2
