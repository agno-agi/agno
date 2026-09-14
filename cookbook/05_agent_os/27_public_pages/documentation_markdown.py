"""Normalize documentation Markdown before indexing, without network or model calls."""

from agno.knowledge.chunking.page import PageMarkdownChunking
from agno.knowledge.reader.utils.mdx import DocumentationMarkdown

source = r"""# Setup

<Steps>
  <Step title="Configure">
    Set API\_KEY, then call the agent.
    <Note>Keep the key in your environment.</Note>
  </Step>
</Steps>
"""

transform = DocumentationMarkdown(profile="fumadocs")
normalized = transform(source, path="/setup.md")
print(normalized)
chunks = PageMarkdownChunking().chunk_texts(normalized)
assert "API_KEY" in normalized and "<Step" not in normalized
assert chunks
print(f"Prepared {len(chunks)} chunks without embedding calls.")

# Pass the same pure transform to Knowledge.sync_pages or async_sync_pages:
# knowledge.sync_pages(url=site_url, transform=transform, index_version="docs-v1")
