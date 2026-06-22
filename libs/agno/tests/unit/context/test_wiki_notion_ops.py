"""Unit tests for the Notion conversion helpers.

These don't hit Notion. They cover the pure functions in
``agno.context.wiki.notion_ops`` plus the input-validation paths on
``NotionDatabaseBackend`` and the ``NotImplementedError`` raised by the
``NotionPageBackend`` stub.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agno.context.wiki import (
    NotionDatabaseBackend,
    NotionPageBackend,
)
from agno.context.wiki.notion_ops import (
    Manifest,
    blocks_to_markdown,
    markdown_to_blocks,
    page_filename,
    parse_page_file,
    render_page_file,
    slugify,
)

# ---------------------------------------------------------------------------
# Slug + filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Deploy Runbook", "deploy-runbook"),
        ("   Lots   of   spaces   ", "lots-of-spaces"),
        ("With/Slashes & Punctuation!", "with-slashes-punctuation"),
        ("Émojis 🎉 Are Stripped", "mojis-are-stripped"),
        ("", "untitled"),
        ("@#$%^&*()", "untitled"),
    ],
)
def test_slugify(title: str, expected: str) -> None:
    assert slugify(title) == expected


def test_page_filename_no_collision() -> None:
    assert page_filename("Hello", "abc-def-123") == "hello.md"


def test_page_filename_collision_suffixes_with_id() -> None:
    used: set[str] = {"hello.md"}
    out = page_filename("Hello", "abc-def-1234567", used=used)
    assert out == "hello-abcdef.md"
    assert out not in used  # caller still has to add it


# ---------------------------------------------------------------------------
# Frontmatter round-trip
# ---------------------------------------------------------------------------


def test_render_and_parse_round_trip() -> None:
    text = render_page_file(
        title="Deploy Runbook",
        page_id="abc-123",
        last_edited="2026-05-13T10:00:00Z",
        body="# Deploy Runbook\n\nBody text",
    )
    fm, body = parse_page_file(text)
    assert fm.notion_page_id == "abc-123"
    assert fm.notion_last_edited == "2026-05-13T10:00:00Z"
    assert fm.title == "Deploy Runbook"
    assert body.strip() == "# Deploy Runbook\n\nBody text"


def test_parse_page_file_missing_frontmatter() -> None:
    fm, body = parse_page_file("# Just a heading\n")
    assert fm.notion_page_id is None
    assert fm.title == ""
    assert body == "# Just a heading\n"


def test_render_omits_blank_id() -> None:
    text = render_page_file(title="New", page_id=None, last_edited=None, body="hi")
    assert "notion_page_id" not in text
    assert "notion_last_edited" not in text


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_manifest_round_trip(tmp_path: Path) -> None:
    m = Manifest(entries={"a.md": "id-1", "b.md": "id-2"})
    path = tmp_path / ".notion-sync.json"
    m.save(path)
    loaded = Manifest.load(path)
    assert loaded.entries == m.entries


def test_manifest_load_missing_file(tmp_path: Path) -> None:
    assert Manifest.load(tmp_path / "missing.json").entries == {}


def test_manifest_load_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / ".notion-sync.json"
    path.write_text("{not json", encoding="utf-8")
    assert Manifest.load(path).entries == {}


def test_manifest_save_is_pretty_json(tmp_path: Path) -> None:
    path = tmp_path / ".notion-sync.json"
    Manifest(entries={"b.md": "id-2", "a.md": "id-1"}).save(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    # Keys serialised sorted so diff noise stays low across syncs.
    assert list(raw["entries"].keys()) == ["a.md", "b.md"]


# ---------------------------------------------------------------------------
# blocks_to_markdown
# ---------------------------------------------------------------------------


def _paragraph(text: str) -> dict:
    return {
        "type": "paragraph",
        "paragraph": {"rich_text": [{"plain_text": text, "annotations": {}}]},
    }


def _heading(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {
        "type": key,
        key: {"rich_text": [{"plain_text": text, "annotations": {}}]},
    }


def test_blocks_to_markdown_headings_and_paragraph() -> None:
    blocks = [_heading(1, "Title"), _paragraph("hello world"), _heading(2, "Sub")]
    md = blocks_to_markdown(blocks)
    assert md == "# Title\n\nhello world\n\n## Sub"


def test_blocks_to_markdown_numbered_list_resets_between_groups() -> None:
    blocks = [
        {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "one", "annotations": {}}]}},
        {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "two", "annotations": {}}]}},
        _paragraph("break"),
        {
            "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": [{"plain_text": "fresh", "annotations": {}}]},
        },
    ]
    md = blocks_to_markdown(blocks)
    assert "1. one" in md
    assert "2. two" in md
    # New list after the paragraph restarts at 1, not 3.
    assert md.endswith("1. fresh")


def test_blocks_to_markdown_todo_checked() -> None:
    blocks = [
        {
            "type": "to_do",
            "to_do": {"rich_text": [{"plain_text": "ship it", "annotations": {}}], "checked": True},
        }
    ]
    assert blocks_to_markdown(blocks) == "- [x] ship it"


def test_blocks_to_markdown_code_block() -> None:
    blocks = [
        {
            "type": "code",
            "code": {
                "rich_text": [{"plain_text": "print('hi')", "annotations": {}}],
                "language": "python",
            },
        }
    ]
    assert blocks_to_markdown(blocks) == "```python\nprint('hi')\n```"


def test_blocks_to_markdown_divider() -> None:
    assert blocks_to_markdown([{"type": "divider", "divider": {}}]) == "---"


def test_blocks_to_markdown_unsupported_block_keeps_placeholder() -> None:
    blocks = [{"type": "callout", "callout": {}}]
    out = blocks_to_markdown(blocks)
    assert "<!-- skipped unsupported block: callout -->" == out


def test_rich_text_annotations() -> None:
    blocks = [
        {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"plain_text": "bold", "annotations": {"bold": True}},
                    {"plain_text": " then ", "annotations": {}},
                    {"plain_text": "code", "annotations": {"code": True}},
                ]
            },
        }
    ]
    assert blocks_to_markdown(blocks) == "**bold** then `code`"


def test_rich_text_link() -> None:
    blocks = [
        {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "plain_text": "Notion",
                        "annotations": {},
                        "text": {"content": "Notion", "link": {"url": "https://notion.so"}},
                    }
                ]
            },
        }
    ]
    assert blocks_to_markdown(blocks) == "[Notion](https://notion.so)"


# ---------------------------------------------------------------------------
# markdown_to_blocks
# ---------------------------------------------------------------------------


def test_markdown_to_blocks_paragraph() -> None:
    blocks = markdown_to_blocks("hello world")
    assert len(blocks) == 1
    assert blocks[0]["type"] == "paragraph"
    assert blocks[0]["paragraph"]["rich_text"][0]["text"]["content"] == "hello world"


def test_markdown_to_blocks_headings() -> None:
    blocks = markdown_to_blocks("# H1\n\n## H2\n\n### H3")
    assert [b["type"] for b in blocks] == ["heading_1", "heading_2", "heading_3"]


def test_markdown_to_blocks_lists_and_todos() -> None:
    md = "- item one\n- item two\n\n1. first\n2. second\n\n- [ ] open\n- [x] done"
    blocks = markdown_to_blocks(md)
    types = [b["type"] for b in blocks]
    assert types == [
        "bulleted_list_item",
        "bulleted_list_item",
        "numbered_list_item",
        "numbered_list_item",
        "to_do",
        "to_do",
    ]
    # Checked-state flows through.
    todos = [b for b in blocks if b["type"] == "to_do"]
    assert todos[0]["to_do"]["checked"] is False
    assert todos[1]["to_do"]["checked"] is True


def test_markdown_to_blocks_code() -> None:
    md = "```python\nprint('hi')\n```"
    blocks = markdown_to_blocks(md)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "code"
    assert blocks[0]["code"]["language"] == "python"
    assert blocks[0]["code"]["rich_text"][0]["text"]["content"] == "print('hi')"


def test_markdown_to_blocks_code_language_fallback() -> None:
    blocks = markdown_to_blocks("```nonsense-lang\nx\n```")
    assert blocks[0]["code"]["language"] == "plain text"


def test_markdown_to_blocks_code_language_alias() -> None:
    blocks = markdown_to_blocks("```py\nx\n```")
    assert blocks[0]["code"]["language"] == "python"


def test_markdown_to_blocks_divider() -> None:
    assert markdown_to_blocks("---")[0]["type"] == "divider"


def test_markdown_to_blocks_quote_collects_contiguous_lines() -> None:
    blocks = markdown_to_blocks("> first line\n> second line")
    assert len(blocks) == 1
    assert blocks[0]["type"] == "quote"
    rich = blocks[0]["quote"]["rich_text"]
    assert "".join(span["text"]["content"] for span in rich) == "first line\nsecond line"


def test_markdown_inline_bold_italic_code_link() -> None:
    blocks = markdown_to_blocks("this is **bold**, *italic*, `code`, and a [link](https://x.test).")
    paragraph = blocks[0]["paragraph"]["rich_text"]
    contents = [(span["text"]["content"], span["annotations"]) for span in paragraph]
    # Verify each styled span has the right annotation flipped on.
    bold = next(c for c in contents if c[0] == "bold")
    italic = next(c for c in contents if c[0] == "italic")
    code = next(c for c in contents if c[0] == "code")
    link_span = next(s for s in paragraph if s["text"].get("link"))
    assert bold[1]["bold"] is True
    assert italic[1]["italic"] is True
    assert code[1]["code"] is True
    assert link_span["text"]["link"]["url"] == "https://x.test"


def test_markdown_to_blocks_ignores_skipped_placeholder() -> None:
    md = "first paragraph\n\n<!-- skipped unsupported block: callout -->\n\nthird paragraph"
    blocks = markdown_to_blocks(md)
    paragraphs = [b for b in blocks if b["type"] == "paragraph"]
    # The placeholder line is dropped, not turned into a paragraph.
    assert len(paragraphs) == 2


# ---------------------------------------------------------------------------
# Round trip: notion blocks -> markdown -> notion blocks
# ---------------------------------------------------------------------------


def test_round_trip_basic_document() -> None:
    md_in = (
        "# Title\n\n"
        "Some paragraph text with **bold** and `code`.\n\n"
        "- one\n- two\n\n"
        "1. step one\n2. step two\n\n"
        "- [ ] todo\n- [x] done\n\n"
        "> quoted\n\n"
        "```python\nx = 1\n```\n\n"
        "---"
    )
    blocks = markdown_to_blocks(md_in)
    # Round-tripping through ``blocks_to_markdown`` should produce a
    # document we can re-parse to the same block sequence.
    md_back = _normalise_md(blocks_to_markdown(_inflate_to_notion_shape(blocks)))
    assert md_back == _normalise_md(md_in)


def _normalise_md(md: str) -> str:
    return "\n".join(line.rstrip() for line in md.strip().split("\n"))


def _inflate_to_notion_shape(blocks: list[dict]) -> list[dict]:
    """``markdown_to_blocks`` emits Notion-API-shaped blocks where each
    span has ``text.content`` but no ``plain_text``. ``blocks_to_markdown``
    expects the Notion-API *response* shape with ``plain_text``. This
    helper copies content -> plain_text so the round-trip test can drive
    both functions end-to-end without an HTTP layer in between.
    """
    out: list[dict] = []
    for block in blocks:
        new = dict(block)
        for key, val in new.items():
            if not isinstance(val, dict) or "rich_text" not in val:
                continue
            new[key] = dict(val)
            new[key]["rich_text"] = [{**span, "plain_text": span["text"]["content"]} for span in val["rich_text"]]
        out.append(new)
    return out


# ---------------------------------------------------------------------------
# Backend input validation + stub
# ---------------------------------------------------------------------------


def test_notion_database_backend_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    with pytest.raises(ValueError, match="NOTION_API_KEY"):
        NotionDatabaseBackend(database_id="abc")


def test_notion_database_backend_requires_database_id() -> None:
    with pytest.raises(ValueError, match="database_id"):
        NotionDatabaseBackend(database_id="", token="ntn_x")


def test_notion_database_backend_uses_env_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NOTION_API_KEY", "ntn_from_env")
    b = NotionDatabaseBackend(database_id="abc", local_path=tmp_path)
    assert b.token == "ntn_from_env"
    assert b.database_id == "abc"


def test_notion_page_backend_stub_raises() -> None:
    with pytest.raises(NotImplementedError, match="roadmap"):
        NotionPageBackend(root_page_id="some-page-id", token="ntn_x")
