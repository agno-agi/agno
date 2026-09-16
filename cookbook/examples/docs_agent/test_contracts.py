"""Check page discovery and the bounded page-reading tool."""

import docs_agent


def test_read_only_discovered_pages():
    results = docs_agent.search_docs("CSV export filters")
    assert results and results[0]["path"] == "docs/exports.md"
    assert "UTF-8" in docs_agent.read_doc(results[0]["path"])
    assert "Page not found" in docs_agent.read_doc("../docs_agent.py")
    assert "Page not found" in docs_agent.read_doc("docs/../../.env")
    assert docs_agent.search_docs("zzznomatchzzz") == []
