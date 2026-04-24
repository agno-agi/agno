import pytest

from agno.os.interfaces.slack.block_kit import (
    Actions,
    BlockKitMessage,
    Button,
    Card,
    InputBlock,
    PlainText,
    PlainTextInput,
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

    def test_allows_all_valid_statuses(self):
        TaskCard(task_id="t1", title="x", status="in_progress")
        TaskCard(task_id="t1", title="x", status="complete")
        TaskCard(task_id="t1", title="x", status="error")

    def test_to_dict_shape(self):
        card = TaskCard(task_id="t1", title="x", status="in_progress")
        dumped = card.to_dict()
        assert dumped["type"] == "task_card"
        assert dumped["task_id"] == "t1"
        assert dumped["title"] == "x"
        assert dumped["status"] == "in_progress"


class TestRichText:
    def test_plain_with_style(self):
        plain = RichTextPlain(text="k:", style=RichTextStyle(bold=True))
        assert plain.style.bold is True
        assert plain.style.italic is None

    def test_to_dict_shape(self):
        section = RichTextSection(elements=[RichTextPlain(text="x", style=RichTextStyle(bold=True))])
        dumped = section.to_dict()
        assert dumped["type"] == "rich_text_section"
        assert len(dumped["elements"]) == 1
        assert dumped["elements"][0]["text"] == "x"

    def test_link_in_section(self):
        section = RichTextSection(
            elements=[
                RichTextPlain(text="see "),
                RichTextLink(url="https://example.com", text="docs"),
            ]
        )
        assert section.elements[0].type == "text"
        assert section.elements[1].type == "link"


class TestCard:
    def test_to_dict_shape(self):
        card = Card(
            title=PlainText(text="Approve?"),
            actions=[Button(action_id="approve", text="Yes")],
            block_id="card_1",
        )
        dumped = card.to_dict()
        assert dumped["type"] == "card"
        assert dumped["block_id"] == "card_1"
        assert len(dumped["actions"]) == 1

    def test_with_subtitle(self):
        card = Card(
            title=PlainText(text="Approve?"),
            subtitle=PlainText(text="tool: search"),
            actions=[Button(action_id="approve", text="Yes")],
        )
        dumped = card.to_dict()
        assert "subtitle" in dumped


class TestBlockKitMessage:
    def test_to_slack_payload_shape(self):
        msg = BlockKitMessage(
            text="fallback",
            blocks=[
                TaskCard(task_id="t1", title="x", status="in_progress"),
                Actions(
                    elements=[
                        Button(action_id="approve", text="Approve", value="t1"),
                    ]
                ),
            ],
        )
        payload = msg.to_slack_payload()
        assert payload["text"] == "fallback"
        assert payload["blocks"][0]["type"] == "task_card"
        assert payload["blocks"][1]["type"] == "actions"

    def test_input_block_in_message(self):
        block = InputBlock(
            label=PlainText(text="field"),
            element=PlainTextInput(action_id="input_field:name"),
        )
        msg = BlockKitMessage(text="x", blocks=[Section(text=PlainText(text="hi")), block])
        payload = msg.to_slack_payload()
        assert payload["blocks"][1]["type"] == "input"

    def test_card_in_message(self):
        card = Card(
            title=PlainText(text="Approve?"),
            actions=[Button(action_id="approve", text="Yes")],
        )
        msg = BlockKitMessage(text="x", blocks=[card])
        payload = msg.to_slack_payload()
        assert payload["blocks"][0]["type"] == "card"


class TestTaskCardSource:
    def test_to_dict(self):
        source = TaskCardSource(url="https://example.com", text="ref")
        dumped = source.to_dict()
        assert dumped["type"] == "url"
        assert dumped["url"] == "https://example.com"
        assert dumped["text"] == "ref"
