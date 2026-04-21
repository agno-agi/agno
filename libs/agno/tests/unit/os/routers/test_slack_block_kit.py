import pytest
from pydantic import ValidationError

from agno.os.interfaces.slack.block_kit import (
    Actions,
    BlockKitMessage,
    Button,
    InputBlock,
    PlainText,
    PlainTextInput,
    RichText,
    RichTextLink,
    RichTextPlain,
    RichTextSection,
    RichTextStyle,
    Section,
    TaskCard,
    TaskCardSource,
)


class TestTaskCard:
    def test_minimal_valid(self):
        card = TaskCard(task_id="approval:abc", title="Approval required", status="in_progress")
        assert card.type == "task_card"
        assert card.details is None
        assert card.output is None

    def test_rejects_pending_status(self):
        # Slack rejects "pending" — task_card only accepts in_progress/completed/error.
        with pytest.raises(ValidationError):
            TaskCard(task_id="t1", title="x", status="pending")

    def test_allows_completed_and_error(self):
        TaskCard(task_id="t1", title="x", status="completed")
        TaskCard(task_id="t1", title="x", status="error")

    def test_requires_title(self):
        with pytest.raises(ValidationError):
            TaskCard(task_id="t1", status="in_progress")

    def test_requires_task_id(self):
        with pytest.raises(ValidationError):
            TaskCard(title="x", status="in_progress")

    def test_dump_excludes_none(self):
        card = TaskCard(task_id="t1", title="x", status="in_progress")
        dumped = card.model_dump(exclude_none=True, mode="json")
        assert dumped == {"type": "task_card", "task_id": "t1", "title": "x", "status": "in_progress"}

    def test_with_details_and_sources(self):
        card = TaskCard(
            task_id="t1",
            title="x",
            status="in_progress",
            details=RichText(elements=[RichTextSection(elements=[RichTextPlain(text="hello")])]),
            sources=[TaskCardSource(url="https://example.com", text="ref")],
        )
        dumped = card.model_dump(exclude_none=True, mode="json")
        assert dumped["details"]["type"] == "rich_text"
        assert dumped["sources"][0]["type"] == "url"


class TestRichText:
    def test_section_requires_elements(self):
        with pytest.raises(ValidationError):
            RichTextSection()

    def test_plain_with_style(self):
        plain = RichTextPlain(text="k:", style=RichTextStyle(bold=True))
        assert plain.style.bold is True
        assert plain.style.italic is None

    def test_style_accepts_dict(self):
        # Row builder passes {"bold": True} — verify Pydantic coerces it.
        section = RichTextSection(elements=[RichTextPlain(text="x", style={"bold": True})])
        assert section.elements[0].style.bold is True

    def test_link_discriminator(self):
        section = RichTextSection(
            elements=[
                RichTextPlain(text="see "),
                RichTextLink(url="https://example.com", text="docs"),
            ]
        )
        assert section.elements[0].type == "text"
        assert section.elements[1].type == "link"

    def test_rich_text_roundtrip_preserves_shape(self):
        rt = RichText(
            elements=[
                RichTextSection(
                    elements=[
                        RichTextPlain(text="path: ", style=RichTextStyle(bold=True)),
                        RichTextPlain(text="/tmp/demo.txt"),
                    ]
                )
            ]
        )
        dumped = rt.model_dump(exclude_none=True, mode="json")
        assert dumped["type"] == "rich_text"
        assert len(dumped["elements"]) == 1
        inner = dumped["elements"][0]["elements"]
        assert inner[0]["style"] == {"bold": True}
        assert "style" not in inner[1]


class TestBlockKitMessage:
    def test_to_slack_payload_shape(self):
        msg = BlockKitMessage(
            text="fallback",
            blocks=[
                TaskCard(task_id="t1", title="x", status="in_progress"),
                Actions(
                    elements=[
                        Button(action_id="approve", text=PlainText(text="Approve"), value="t1"),
                    ]
                ),
            ],
        )
        payload = msg.to_slack_payload()
        assert payload["text"] == "fallback"
        assert [b["type"] for b in payload["blocks"]] == ["task_card", "actions"]

    def test_rejects_unknown_block_type(self):
        # extra='forbid' — keeps payloads clean against typos.
        with pytest.raises(ValidationError):
            BlockKitMessage(text="x", blocks=[{"type": "bogus"}])

    def test_input_block_in_union(self):
        # InputBlock used by user_input/user_feedback/external_execution rows.
        block = InputBlock(
            label=PlainText(text="field"),
            element=PlainTextInput(action_id="input_field:name"),
        )
        msg = BlockKitMessage(text="x", blocks=[Section(text=PlainText(text="hi")), block])
        payload = msg.to_slack_payload()
        assert payload["blocks"][1]["type"] == "input"
