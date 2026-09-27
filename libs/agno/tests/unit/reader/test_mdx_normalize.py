import pytest

from agno.knowledge.reader.utils.mdx import DocumentationMarkdown, normalize_mdx

normalize_page = DocumentationMarkdown(profile="fumadocs")

STEPS = r"""# Agent with Memory (/docs/models/x/usage/memory)

## Usage [#usage]

<Steps>
    <Step title="Set up your virtual environment">
      <CodeBlockTabs defaultValue="Mac">
        <CodeBlockTabsList>
          <CodeBlockTabsTrigger value="Mac">
            Mac
          </CodeBlockTabsTrigger>

          <CodeBlockTabsTrigger value="Windows">
            Windows
          </CodeBlockTabsTrigger>
        </CodeBlockTabsList>

        <CodeBlockTab value="Mac">
          ```bash
          uv venv --python 3.12
          source .venv/bin/activate
          ```
        </CodeBlockTab>

        <CodeBlockTab value="Windows">
          ```bash
          uv venv --python 3.12
          .venv\Scripts\activate
          ```
        </CodeBlockTab>
      </CodeBlockTabs>
    </Step>

  <Step title="Run Agent">
    Save the code above as `memory.py`, then run:

    ```bash
    python memory.py
    ```
  </Step>
</Steps>
"""

STEPS_EXPECTED = r"""# Agent with Memory (/docs/models/x/usage/memory)

## Usage [#usage]

**Step 1: Set up your virtual environment**

**Mac**

```bash
uv venv --python 3.12
source .venv/bin/activate
```

**Windows**

```bash
uv venv --python 3.12
.venv\Scripts\activate
```

**Step 2: Run Agent**

Save the code above as `memory.py`, then run:

```bash
python memory.py
```
"""


def test_steps_and_code_tabs_become_labelled_markdown():
    assert normalize_mdx(STEPS) == STEPS_EXPECTED


def test_normalisation_is_idempotent_and_leaves_plain_pages_alone():
    assert normalize_mdx(STEPS_EXPECTED) == STEPS_EXPECTED
    plain = "# T\n\nText with `<your-api-key>` and <id> placeholders.\n\n<topic>\n"
    assert normalize_mdx(plain) == plain


def test_callouts():
    single = "<Note>\n  With `x=True`, hooks run in the background.\n</Note>\n"
    assert normalize_mdx(single) == "**Note:** With `x=True`, hooks run in the background.\n"
    assert normalize_mdx("<Tip>Short.</Tip>\n") == "**Tip:** Short.\n"
    assert normalize_mdx('<Callout type="warning">\n  Careful.\n</Callout>\n') == "**Warning:** Careful.\n"
    multi = "<Warning>\n  Run:\n\n  ```bash\n  rm -rf tmp\n  ```\n</Warning>\n\nAfter.\n"
    assert normalize_mdx(multi) == "**Warning:**\nRun:\n\n```bash\nrm -rf tmp\n```\n\nAfter.\n"


def test_cards_accordions_fields_and_tooltips():
    cards = (
        '<CardGroup cols="2">\n'
        '  <Card title="Setup Guide" icon="rocket" href="/slack/setup">\n'
        "    Create a Slack App from scratch\n  </Card>\n\n"
        '  <Card title="Features" href="/slack/features" />\n'
        "</CardGroup>\n"
    )
    assert normalize_mdx(cards) == (
        "- [Setup Guide](/slack/setup): Create a Slack App from scratch\n\n- [Features](/slack/features)\n"
    )
    accordion = (
        '<AccordionGroup>\n  <Accordion title="MissingGreenlet exception">\n    Use the async engine.\n  </Accordion>\n'
        "</AccordionGroup>\n"
    )
    assert normalize_mdx(accordion) == "**MissingGreenlet exception**\n\nUse the async engine.\n"
    field = '<ResponseField name="name" type="str" required>\n  Name of the directory. `--name`\n</ResponseField>\n'
    assert normalize_mdx(field) == "- `name` (str, required): Name of the directory. `--name`\n"
    badge = (
        '<Badge icon="code-branch" color="orange">\n'
        '  <Tooltip tip="Introduced in v2.2.1" cta="View release notes" href="https://x">\n    v2.2.1\n  </Tooltip>\n'
        "</Badge>\n"
    )
    assert normalize_mdx(badge) == "*Introduced in v2.2.1*\n"


def test_media_html_and_unknown_components():
    frame = (
        '<Frame caption="AgentOS API">\n'
        '  <ImageZoom src="/docs/videos/first-agent-api.gif" alt="AgentOS API" width="800" height="524" />\n'
        "</Frame>\n"
    )
    assert normalize_mdx(frame) == "![AgentOS API](/docs/videos/first-agent-api.gif)\n*AgentOS API*\n"
    assert (
        normalize_mdx('<video className="w-full" src="/docs/videos/demo.mp4" />\n')
        == "[Video](/docs/videos/demo.mp4)\n"
    )
    heading = '<h2 id="get-started" style="{ marginTop: "1.5rem" }">\n  Get started\n</h2>\n\n* [Build](/first-agent)\n'
    assert normalize_mdx(heading) == "## Get started\n\n* [Build](/first-agent)\n"
    assert normalize_mdx("a\n\n<br />\n\n<div style=\"{ marginTop: '2rem' }\">\n  inside\n</div>\n") == "a\n\ninside\n"
    assert normalize_mdx("<Whatever prop={1}>\n  kept\n</Whatever>\n") == "kept\n"
    # unclosed tags: the tag line goes, the rest is kept as written
    assert normalize_mdx('<Steps>\n  <Step title="Only">\n    one\n') == "**Step 1: Only**\n\n    one\n"


def test_fences_and_nested_lists_are_preserved():
    fenced = '```mdx\n<Steps>\n  <Step title="x">\n</Steps>\n```\n'
    assert normalize_mdx(fenced) == fenced
    nested = '<Steps>\n  <Step title="A">\n    - one\n      - nested\n    - two\n  </Step>\n</Steps>\n'
    assert normalize_mdx(nested) == "**Step 1: A**\n\n- one\n  - nested\n- two\n"
    numbered = '<Steps>\n<Step title="A">\na\n</Step>\n</Steps>\n\n<Steps>\n<Step title="B">\nb\n</Step>\n</Steps>\n'
    assert normalize_mdx(numbered) == "**Step 1: A**\n\na\n\n**Step 1: B**\n\nb\n"
    # inner list has two steps so the outer counter resuming at 2 (not 3) is observable
    nested_steps = (
        '<Steps>\n<Step title="A">\n<Steps>\n<Step title="i1">\nx\n</Step>\n<Step title="i2">\ny\n</Step>\n</Steps>\n'
        '</Step>\n<Step title="B">\nb\n</Step>\n</Steps>\n'
    )
    assert normalize_mdx(nested_steps) == (
        "**Step 1: A**\n\n**Step 1: i1**\n\nx\n\n**Step 2: i2**\n\ny\n\n**Step 2: B**\n\nb\n"
    )


@pytest.mark.parametrize(
    "opening,inner,closing",
    [("````markdown", "```python", "````"), ("~~~markdown", "```", "~~~~"), ("```mdx", "```not-a-close", "```")],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_normalization_preserves_literal_content_inside_nested_fences(opening, inner, closing, wrapped):
    code = f'{opening}\n{inner}\n</Note>\n<Note>literal example</Note>\n\n\nTOKEN = "A\\_B &amp; C"\n{closing}\n'
    after = "\n<Note>Outside &amp; prose\\_identifier.</Note>\n"
    raw = f"<Note>\n{code}</Note>\n{after}" if wrapped else code + after
    expected = ("**Note:**\n" if wrapped else "") + code + "\n**Note:** Outside & prose_identifier.\n"
    assert normalize_page(raw, path="/example.md") == expected


def test_unescape_prose_strips_markdown_escapes_outside_fences():
    raw = (
        "Set QWEN\\_API\\_KEY and pass List\\[Message] or a \\*star\\*\n\n```\nkeep \\_ this\n```\n\n"
        "| a \\| b |\n\nRun `%APPDATA%\\Claude\\` and `\\[literal]`\n"
    )
    assert normalize_page(raw, path="/page.md") == (
        "Set QWEN_API_KEY and pass List[Message] or a *star*\n\n```\nkeep \\_ this\n```\n\n"
        "| a \\| b |\n\nRun `%APPDATA%\\Claude\\` and `[literal]`\n"
    )


def test_unescape_prose_leaves_fences_alone():
    raw = "Say &#x22;hi&#x22;\n\n```\n&#x2A; kept\n```\n"
    assert normalize_page(raw, path="/page.md") == 'Say "hi"\n\n```\n&#x2A; kept\n```\n'


def test_default_profile_preserves_authored_markdown_verbatim():
    raw = "\r\n<Note>Literal</Note>\r\n\r\n\r\n    code &amp; \\_\r\n\r\n"
    assert DocumentationMarkdown()(raw, path="/plain.md") == raw


def test_profiles_and_serializer_override():
    raw = "> ## Documentation Index\n> See /llms.txt\n\n<Note>Use API\\_KEY &amp; tokens.</Note>\n"
    assert DocumentationMarkdown(profile="fumadocs")(raw, path="/x.md") == "**Note:** Use API_KEY & tokens.\n"
    expected = "**Note:** Use API\\_KEY &amp; tokens.\n"
    assert DocumentationMarkdown(profile="mintlify")(raw, path="/x.md") == expected
    assert DocumentationMarkdown(profile="fumadocs", unescape_serializer=False)(raw, path="/x.md") == expected
    assert DocumentationMarkdown(profile="mintlify", unescape_serializer=True)(raw, path="/x.md") == normalize_page(
        raw, path="/x.md"
    )


def test_only_leading_preamble_is_removed_and_can_be_disabled():
    text = "> ## Documentation Index\n> See /llms.txt\n\n# T\n\n> ## Documentation Index\n> Keep this.\n"
    assert normalize_page(text, path="/x.md") == "# T\n\n> ## Documentation Index\n> Keep this.\n"
    assert DocumentationMarkdown(profile="fumadocs", strip_index_preamble=False)(text, path="/x.md") == text


def test_component_overrides_are_isolated_and_receive_normalized_children():
    aliases = {"Aside": "Warning"}
    seen = []

    def render(attrs, content):
        seen.append((dict(attrs), content))
        return f"{attrs['title']}: {content.strip()}"

    transform = DocumentationMarkdown(
        profile="mintlify", component_aliases=aliases, component_renderers={"Panel": render}
    )
    aliases["Aside"] = "Tip"
    raw = '<Panel title="安全" expression={never_execute()}>\n<Aside>慎重に。</Aside>\n</Panel>\n'
    assert transform(raw, path="/x.md") == "安全: **Warning:** 慎重に。\n"
    assert seen[0][0] == {"title": "安全", "expression": "never_execute()"}
    assert normalize_mdx("<Aside>text</Aside>\n") == "text\n"


def test_empty_profile_output_and_invalid_profile():
    with pytest.raises(ValueError, match="empty page"):
        normalize_page("> ## Documentation Index\n> index only\n", path="/x.md")
    with pytest.raises(ValueError, match="Unknown"):
        DocumentationMarkdown(profile="unknown")


def test_serializer_order_and_non_idempotent_entity_limit_are_explicit():
    # Decode after component rendering so escaped examples remain literal this pass.
    assert normalize_page("&lt;Note&gt;example&lt;/Note&gt;\n", path="/x.md") == "<Note>example</Note>\n"
    assert normalize_page("&amp;amp;\n", path="/x.md") == "&amp;\n"
    assert normalize_page("&amp;\n", path="/x.md") == "&\n"


@pytest.mark.parametrize("profile", ["fumadocs", "mintlify"])
def test_unicode_and_line_endings(profile):
    assert DocumentationMarkdown(profile=profile)("<Note>説明 🙂</Note>\r\n", path="/x.md") == "**Note:** 説明 🙂\n"
