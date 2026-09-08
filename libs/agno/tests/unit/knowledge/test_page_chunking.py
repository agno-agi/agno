from agno.knowledge.chunking.page import PageMarkdownChunking, _split_long, clean_heading, page_intro

PAGE = """# Agents

> Intro line.

Agents are the core.

## Creating an agent

```python
from agno.agent import Agent

agent = Agent()
# a heading-looking line inside a fence must not split:
# ## not a heading
```

### Options

More detail.

## Memory

Memory text.
"""


def body_of(chunk: str) -> str:
    """The chunk after its context line and breadcrumb line."""
    return chunk.split("\n\n", 2)[2]


def test_chunks_open_with_context_line_then_breadcrumb():
    chunks = PageMarkdownChunking(chunk_size=2000).chunk_texts(PAGE)
    assert len(chunks) == 3
    assert chunks[0].startswith("Agents: Intro line.\n\nAgents\n\n# Agents")
    assert chunks[1].startswith("Agents: Intro line.\n\nAgents › Creating an agent\n\n## Creating an agent")
    assert "```python\nfrom agno.agent import Agent\n\nagent = Agent()" in chunks[1]
    assert "### Options" in chunks[1]
    assert chunks[2].startswith("Agents: Intro line.\n\nAgents › Memory")


def test_page_intro_is_the_first_prose_paragraph():
    assert page_intro(PAGE) == "Intro line."
    assert page_intro("# T\n\n```python\ncode\n```\n\nAfter the code.\n") == "After the code."
    assert page_intro("# T\n\n**Step 1: Install**\n\nRun pip.\n") == "Run pip."
    assert page_intro("# T\n\nOne line.\nSecond line.\n\nNext paragraph.\n") == "One line. Second line."
    assert page_intro("# T\n\n" + "x" * 400) == "x" * 300
    assert page_intro("# T\n\n## Only headings\n") == ""
    # No prose, no context line; an intro that starts with the title is not prefixed twice.
    assert PageMarkdownChunking().chunk_texts("# T\n\n## A\n\n```\ncode\n```\n")[0].startswith("T › A\n\n")
    assert PageMarkdownChunking().chunk_texts("# T\n\nT is a tool.\n")[0].startswith("T is a tool.\n\nT\n\n# T")


def test_long_sections_split_on_paragraphs_not_mid_line():
    body = "# T\n\n" + "\n\n".join(f"paragraph {i} " + "x" * 300 for i in range(12))
    chunks = PageMarkdownChunking(chunk_size=1000).chunk_texts(body)
    assert len(chunks) > 1
    # slack: the context and breadcrumb lines are prepended after the size check
    assert all(len(c) <= 1000 + 60 + 300 for c in chunks)
    original = set(body.splitlines())
    assert all(line in original for c in chunks for line in body_of(c).splitlines())
    assert all(body_of(c).startswith("paragraph") for c in chunks[1:])
    joined = "\n".join(chunks)
    assert all(f"paragraph {i} " in joined for i in range(12))


FUMADOCS_PAGE = """# Use Agno with Coding Agents (/docs/coding-agents)

Intro.

## Option 1: Add the docs as an MCP server [#option-1-add-the-docs-as-an-mcp-server]

Add it.
"""


def test_fumadocs_title_and_anchor_suffixes_are_stripped_from_breadcrumbs():
    chunks = PageMarkdownChunking(chunk_size=2000).chunk_texts(FUMADOCS_PAGE)
    assert chunks[0].startswith(
        "Use Agno with Coding Agents: Intro.\n\nUse Agno with Coding Agents\n\n"
        "# Use Agno with Coding Agents (/docs/coding-agents)"
    )
    assert chunks[1].startswith(
        "Use Agno with Coding Agents: Intro.\n\n"
        "Use Agno with Coding Agents › Option 1: Add the docs as an MCP server\n\n## Option 1"
    )
    assert (
        clean_heading("Basic RBAC (Symmetric) (/docs/agent-os/usage/rbac/basic)", page_title=True)
        == "Basic RBAC (Symmetric)"
    )
    assert clean_heading("Welcome to Agno (/docs/)", page_title=True) == "Welcome to Agno"
    assert clean_heading("Next steps [#next-steps]") == "Next steps"
    assert clean_heading("Plain (note)") == "Plain (note)"


def test_long_fences_are_split_with_balanced_fences():
    body = "# T\n\n```python\n" + "\n".join(f"line {i} " + "x" * 80 for i in range(70)) + "\n```\n"
    chunks = PageMarkdownChunking(chunk_size=2000).chunk_texts(body)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert sum(1 for line in chunk.splitlines() if line.startswith("```")) % 2 == 0
        # slack: context line, breadcrumb and the re-opened/closed fence are added after the size check
        assert len(chunk) <= 2000 + 120 + 300
    # no prose on this page, so no context line: the breadcrumb is the first line
    assert all(chunk.split("\n\n", 1)[1].startswith("```python") for chunk in chunks[1:])
    joined = "\n".join(chunks)
    assert all(f"line {i} " in joined for i in range(70))


def test_long_four_character_fences_keep_inner_triple_fences_literal():
    before = [f"before {i} " + "x" * 70 for i in range(30)]
    after = [f"after {i} " + "y" * 70 for i in range(30)]
    for opener, inner_opener, inner_closer, closer in (
        ("````python", "```markdown", "```", "````"),
        ("~~~~python", "~~~markdown", "~~~", "~~~~"),
    ):
        body = "\n".join(["# T", "", opener, *before, inner_opener, "## literal heading", inner_closer, *after, closer])
        chunks = PageMarkdownChunking(chunk_size=1000).chunk_texts(body)

        assert len(chunks) >= 4
        assert page_intro(body) == ""
        assert all("T › literal heading" not in chunk for chunk in chunks)
        for chunk in chunks:
            delimiters = [line.strip() for line in chunk.splitlines() if line.strip().startswith(opener[0] * 3)]
            assert delimiters[0] == opener
            assert delimiters[-1] == closer

        lines = [line.strip() for chunk in chunks for line in chunk.splitlines()]
        assert lines.count(inner_opener) == lines.count(inner_closer) == 1
        assert lines.count("## literal heading") == 1
        assert all(lines.count(line) == 1 for line in before + after)


def test_closing_fence_stays_with_its_block():
    """Regression for _split_long's 'closing fence stays with its block': the block is at 1997 chars when the
    closing ``` arrives and appending it crosses the 2000 limit; it must still land in piece 0, never open piece 1."""
    after = ("after " * 100).strip()  # longer than limit // 4, so it is a real second piece
    body = "intro\n\n```python\n" + "\n".join("y" * 90 for _ in range(21)) + "\n" + "y" * 68 + "\n```\n\n" + after
    pieces = _split_long(body, 2000)
    assert len(pieces) == 2
    assert pieces[0].endswith("```") and pieces[1] == after.strip()


def test_short_tail_stays_with_the_piece_before_it():
    body = "x" * 1900 + "\n\n" + "y" * 150
    assert _split_long(body, 2000) == [body]
    # a long fence never leaves a continuation shorter than a quarter of the limit
    fence = "```python\n" + "\n".join("z" * 90 for _ in range(45)) + "\n```"
    pieces = _split_long(fence, 2000)
    assert len(pieces) == 2 and all(len(p) >= 500 for p in pieces)
    assert all(p.startswith("```python") and p.endswith("```") for p in pieces)
