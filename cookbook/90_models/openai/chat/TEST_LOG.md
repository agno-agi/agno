# TEST_LOG

### citations.py

**Status:** PASS

**Description:** Runs `OpenAIChat(id="gpt-4o-search-preview")` with a web-search query and prints the response. Verifies that the model's `url_citation` annotations are surfaced on `response.citations.urls`.

**Result:** Content rendered with a populated Citations panel; `response.citations.urls` contains title/url pairs from the web search.

---
