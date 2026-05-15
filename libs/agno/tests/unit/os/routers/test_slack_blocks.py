from typing import Any, Dict

from agno.models.response import ToolExecution
from agno.os.interfaces.slack.builders import build_pause_message
from agno.os.interfaces.slack.ids import (
    ACTION_EXTERNAL_RESULT,
    ACTION_FEEDBACK_SELECT,
    ACTION_INPUT_FIELD_PREFIX,
    ACTION_ROW_APPROVE,
    ACTION_ROW_REJECT,
    ACTION_SUBMIT,
    parse_row_block_id,
    pause_block_id,
    row_block_id,
)
from agno.os.interfaces.slack.interactions import parse_submit_payload
from agno.run.requirement import RunRequirement, UserFeedbackQuestion
from agno.tools.function import UserFeedbackOption, UserInputField

# -- Helpers --


def _make_tool_execution(**overrides) -> ToolExecution:
    defaults = dict(tool_name="do_something", tool_args={"path": "/tmp/demo.txt"})
    defaults.update(overrides)
    return ToolExecution(**defaults)


def _make_requirement(req_id: str = "r1", **te_overrides) -> RunRequirement:
    return RunRequirement(tool_execution=_make_tool_execution(**te_overrides), id=req_id)


def _submit_payload(state_values=None, message_blocks=None) -> Dict[str, Any]:
    return {
        "state": {"values": state_values or {}},
        "message": {"blocks": message_blocks or []},
    }


# -- pause_type property --


class TestPauseType:
    def test_user_feedback_wins(self):
        # Priority: feedback > external > input > confirmation (most specific wins)
        req = _make_requirement(
            user_feedback_schema=[UserFeedbackQuestion(question="?", options=[UserFeedbackOption(label="A")])],
            requires_user_input=True,
            requires_confirmation=True,
        )
        assert req.pause_type == "user_feedback"

    def test_external_execution_wins_over_input_and_confirmation(self):
        req = _make_requirement(
            external_execution_required=True,
            requires_user_input=True,
            requires_confirmation=True,
        )
        assert req.pause_type == "external_execution"

    def test_user_input_wins_over_confirmation(self):
        req = _make_requirement(requires_user_input=True, requires_confirmation=True)
        assert req.pause_type == "user_input"

    def test_defaults_to_confirmation(self):
        req = _make_requirement(requires_confirmation=True)
        assert req.pause_type == "confirmation"

    def test_missing_tool_execution_is_confirmation(self):
        req = _make_requirement()
        req.tool_execution = None
        assert req.pause_type == "confirmation"


# -- row_block_id / parse_row_block_id --


class TestRowBlockId:
    def test_pending_round_trip(self):
        assert parse_row_block_id(row_block_id("r1", "confirmation")) == {
            "req_id": "r1",
            "kind": "confirmation",
            "status": "pending",
        }

    def test_decided_round_trip(self):
        assert parse_row_block_id(row_block_id("r1", "confirmation", decided="approve")) == {
            "req_id": "r1",
            "kind": "confirmation",
            "status": "decided",
            "decided": "approve",
        }

    def test_non_row_prefix_returns_none(self):
        assert parse_row_block_id("pause:A1") is None
        assert parse_row_block_id("rowact:r1:confirmation") is None


# -- Confirmation row --


class TestConfirmationRow:
    def test_block_type_is_card(self):
        # Confirmation renders as a single Card with title (tool name),
        # subtitle (args), and embedded Approve/Deny buttons. Coexists with
        # the streaming plan/task_card above; dropped on decision via
        # chat.update.
        req = _make_requirement(tool_name="delete_file")
        blocks = build_pause_message("A1", [req])
        assert [b.type for b in blocks] == ["card"]

    def test_card_title_contains_tool_name(self):
        card = build_pause_message("A1", [_make_requirement(tool_name="delete_file")])[0]
        assert card.title.text == "*delete_file*"

    def test_card_body_renders_args(self):
        card = build_pause_message("A1", [_make_requirement(tool_name="delete_file", tool_args={"path": "/tmp/x"})])[0]
        assert "path" in card.body.text
        assert "/tmp/x" in card.body.text

    def test_button_action_ids(self):
        card = build_pause_message("A1", [_make_requirement()])[0]
        assert [el.action_id for el in card.actions] == [ACTION_ROW_APPROVE, ACTION_ROW_REJECT]

    def test_button_value_routing(self):
        # _handle_row_click splits on "|" to recover (req_id, run_id, awaiting_ts).
        card = build_pause_message("A1", [_make_requirement()])[0]
        assert card.actions[0].value == "r1|A1|"
        assert card.actions[1].value == "r1|A1|"

    def test_buttons_no_confirm_dialogs(self):
        # Direct action without confirmation popup for faster UX
        card = build_pause_message("A1", [_make_requirement()])[0]
        assert card.actions[0].confirm is None
        assert card.actions[1].confirm is None


# -- User-input row --


class TestUserInputRow:
    def test_block_types(self):
        req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="to_address", field_type=str)],
        )
        blocks = build_pause_message("A1", [req])
        # Input fields + global Submit. Header lives in the plan timeline.
        assert [b.type for b in blocks] == ["input", "actions"]

    def test_per_field_block_ids_are_unique(self):
        # Regression — Slack rejects messages with duplicate block_ids.
        req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[
                UserInputField(name="to_address", field_type=str),
                UserInputField(name="subject", field_type=str),
                UserInputField(name="body", field_type=str),
            ],
        )
        input_blocks = [b for b in build_pause_message("A1", [req]) if b.type == "input"]
        ids = [b.block_id for b in input_blocks]
        assert len(set(ids)) == len(ids) == 3

    def test_bool_field_uses_static_select(self):
        req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="force", field_type=bool)],
        )
        block = build_pause_message("A1", [req])[0]
        assert block.element.type == "static_select"
        assert [o.value for o in block.element.options] == ["true", "false"]

    def test_list_field_uses_multiline(self):
        req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="tags", field_type=list)],
        )
        block = build_pause_message("A1", [req])[0]
        assert block.element.multiline is True


# -- User-feedback row --


class TestUserFeedbackRow:
    def test_multi_select_uses_checkboxes(self):
        req = _make_requirement(
            user_feedback_schema=[
                UserFeedbackQuestion(
                    question="Pick toppings",
                    options=[UserFeedbackOption(label="Mushroom"), UserFeedbackOption(label="Olives")],
                    multi_select=True,
                ),
            ],
        )
        block = build_pause_message("A1", [req])[0]
        assert block.element.type == "checkboxes"
        assert block.element.action_id == f"{ACTION_FEEDBACK_SELECT}:0"

    def test_single_select_uses_static_select(self):
        req = _make_requirement(
            user_feedback_schema=[
                UserFeedbackQuestion(
                    question="Pick one",
                    options=[UserFeedbackOption(label="A"), UserFeedbackOption(label="B")],
                ),
            ],
        )
        block = build_pause_message("A1", [req])[0]
        assert block.element.type == "static_select"

    def test_question_index_in_block_id(self):
        req = _make_requirement(
            user_feedback_schema=[
                UserFeedbackQuestion(question="q0", options=[UserFeedbackOption(label="A")]),
                UserFeedbackQuestion(question="q1", options=[UserFeedbackOption(label="B")]),
            ],
        )
        input_blocks = [b for b in build_pause_message("A1", [req]) if b.type == "input"]
        prefix = row_block_id("r1", "user_feedback")
        assert [b.block_id for b in input_blocks] == [f"{prefix}:q0", f"{prefix}:q1"]


# -- External-execution row --


class TestExternalExecutionRow:
    def test_block_types(self):
        req = _make_requirement(tool_name="run_shell", external_execution_required=True)
        blocks = build_pause_message("A1", [req])
        assert [b.type for b in blocks] == ["input", "actions"]

    def test_multiline_plain_text_input(self):
        req = _make_requirement(external_execution_required=True)
        block = build_pause_message("A1", [req])[0]
        assert block.element.type == "plain_text_input"
        assert block.element.multiline is True
        assert block.element.action_id == ACTION_EXTERNAL_RESULT


# -- Global Submit --


class TestGlobalSubmit:
    def test_confirmation_only_skips_submit(self):
        blocks = build_pause_message("A1", [_make_requirement(req_id="r1"), _make_requirement(req_id="r2")])
        # Tail is per-row Approve/Deny, not a global Submit.
        assert blocks[-1].block_id != pause_block_id("A1")

    def test_mixed_pause_adds_submit(self):
        confirm = _make_requirement(req_id="r1", tool_name="delete_file")
        input_req = _make_requirement(
            req_id="r2",
            requires_user_input=True,
            user_input_schema=[UserInputField(name="x", field_type=str)],
        )
        blocks = build_pause_message("A1", [confirm, input_req])
        assert blocks[-1].block_id == pause_block_id("A1")
        assert blocks[-1].elements[0].action_id == ACTION_SUBMIT


# -- parse_submit_payload --


class TestParseSubmitPayload:
    def test_user_input_reads_per_field_block_ids(self):
        req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[
                UserInputField(name="to_address", field_type=str),
                UserInputField(name="subject", field_type=str),
            ],
        )
        prefix = row_block_id("r1", "user_input")
        payload = _submit_payload(
            state_values={
                f"{prefix}:to_address": {
                    f"{ACTION_INPUT_FIELD_PREFIX}to_address": {"type": "plain_text_input", "value": "you@example.com"},
                },
                f"{prefix}:subject": {
                    f"{ACTION_INPUT_FIELD_PREFIX}subject": {"type": "plain_text_input", "value": "Q1 results"},
                },
            }
        )
        decisions, errors = parse_submit_payload(payload, [req])
        assert errors == []
        assert decisions[0].input_values == {"to_address": "you@example.com", "subject": "Q1 results"}

    def test_user_input_bool_value_returned_from_slack(self):
        req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="force", field_type=bool)],
        )
        prefix = row_block_id("r1", "user_input")
        payload = _submit_payload(
            state_values={
                f"{prefix}:force": {
                    f"{ACTION_INPUT_FIELD_PREFIX}force": {
                        "type": "static_select",
                        "selected_option": {"value": "true"},
                    },
                },
            }
        )
        decisions, errors = parse_submit_payload(payload, [req])
        assert errors == []
        assert decisions[0].input_values == {"force": "true"}

    def test_user_input_list_value_returned_from_slack(self):
        req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="tags", field_type=list)],
        )
        prefix = row_block_id("r1", "user_input")
        payload = _submit_payload(
            state_values={
                f"{prefix}:tags": {
                    f"{ACTION_INPUT_FIELD_PREFIX}tags": {"type": "plain_text_input", "value": '["a","b"]'},
                },
            }
        )
        decisions, errors = parse_submit_payload(payload, [req])
        assert errors == []
        assert decisions[0].input_values == {"tags": '["a","b"]'}

    def test_user_input_plain_text_value_does_not_require_json_parsing(self):
        req = _make_requirement(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="tags", field_type=list)],
        )
        prefix = row_block_id("r1", "user_input")
        payload = _submit_payload(
            state_values={
                f"{prefix}:tags": {
                    f"{ACTION_INPUT_FIELD_PREFIX}tags": {"type": "plain_text_input", "value": "not json"},
                },
            }
        )
        decisions, errors = parse_submit_payload(payload, [req])
        assert errors == []
        assert decisions[0].input_values == {"tags": "not json"}

    def test_confirmation_legacy_decided_block_id(self):
        # Backwards-compat — older messages use section + decided block_id.
        req = _make_requirement(tool_name="delete_file")
        payload = _submit_payload(
            message_blocks=[
                {"block_id": row_block_id("r1", "confirmation", decided="approve"), "type": "section"},
            ]
        )
        decisions, errors = parse_submit_payload(payload, [req])
        assert errors == []
        assert decisions[0].approved is True

    def test_confirmation_legacy_decided_block_id_reject(self):
        # Deny click path: _handle_action synthesizes this exact block_id
        # shape when deleting the Card, so parser must recognize reject here.
        req = _make_requirement(tool_name="delete_file")
        payload = _submit_payload(
            message_blocks=[
                {"block_id": row_block_id("r1", "confirmation", decided="reject"), "type": "section"},
            ]
        )
        decisions, errors = parse_submit_payload(payload, [req])
        assert errors == []
        assert decisions[0].approved is False

    def test_confirmation_without_click_requires_explicit_decision(self):
        # Submit without clicking Approve/Deny returns validation error
        req = _make_requirement(tool_name="delete_file")
        decisions, errors = parse_submit_payload(_submit_payload(), [req])
        assert decisions[0].approved is None
        assert len(errors) == 1
        assert errors[0].message == "Approval decision required"

    def test_external_execution_strips_whitespace(self):
        # Strip avoids accidental whitespace from pasted terminal output.
        req = _make_requirement(external_execution_required=True)
        prefix = row_block_id("r1", "external_execution")
        payload = _submit_payload(
            state_values={
                f"{prefix}:result": {
                    ACTION_EXTERNAL_RESULT: {"type": "plain_text_input", "value": "  ok\n"},
                },
            }
        )
        decisions, errors = parse_submit_payload(payload, [req])
        assert errors == []
        assert decisions[0].external_result == "ok"

    def test_external_execution_empty_value_records_error(self):
        req = _make_requirement(external_execution_required=True)
        prefix = row_block_id("r1", "external_execution")
        payload = _submit_payload(
            state_values={
                f"{prefix}:result": {
                    ACTION_EXTERNAL_RESULT: {"type": "plain_text_input", "value": "   "},
                },
            }
        )
        _, errors = parse_submit_payload(payload, [req])
        assert len(errors) == 1
        assert errors[0].requirement_id == "r1"


# -- _build_confirmation_toggle_card --


class TestBuildConfirmationToggleCard:
    def test_approve_selected_has_primary_style(self):
        from agno.os.interfaces.slack.builders import build_confirmation_toggle_card

        card = build_confirmation_toggle_card(
            req_id="r1",
            run_id="A1",
            awaiting_ts="123.456",
            tool_name="delete_file",
            body_text="• path: `/tmp/x`",
            selected="approve",
        )
        assert card.block_id == "rowact:r1:confirmation:selected:approve"
        approve_btn = card.actions[0]
        assert approve_btn.text.text == "Approved"
        assert approve_btn.style == "primary"

    def test_deny_selected_has_danger_style(self):
        from agno.os.interfaces.slack.builders import build_confirmation_toggle_card

        card = build_confirmation_toggle_card(
            req_id="r1",
            run_id="A1",
            awaiting_ts=None,
            tool_name="delete_file",
            body_text="• path: `/tmp/x`",
            selected="deny",
        )
        assert card.block_id == "rowact:r1:confirmation:selected:deny"
        deny_btn = card.actions[1]
        assert deny_btn.text.text == "Denied"
        assert deny_btn.style == "danger"

    def test_preserves_tool_name_and_body(self):
        from agno.os.interfaces.slack.builders import build_confirmation_toggle_card

        card = build_confirmation_toggle_card(
            req_id="r1",
            run_id="A1",
            awaiting_ts=None,
            tool_name="cancel_subscription",
            body_text="• customer_id: `C-42`",
            selected="approve",
        )
        assert card.title.text == "*cancel_subscription*"
        assert card.body.text == "• customer_id: `C-42`"


# -- response_blocks --


class TestResponseBlocks:
    def test_strips_actions_from_cards(self):
        from agno.os.interfaces.slack.builders import response_blocks

        original = [{"type": "card", "block_id": "rowact:r1:confirmation", "actions": [{"type": "button"}]}]
        result = response_blocks(original, {}, [])
        assert "actions" not in result[0]

    def test_converts_selected_approve_to_approved_title(self):
        from agno.os.interfaces.slack.builders import response_blocks

        original = [
            {
                "type": "card",
                "block_id": "rowact:r1:confirmation:selected:approve",
                "title": {"type": "mrkdwn", "text": "*delete_file*"},
                "actions": [],
            }
        ]
        result = response_blocks(original, {}, [])
        assert result[0]["title"]["text"] == "*Approved:* delete_file"

    def test_converts_selected_deny_to_denied_title(self):
        from agno.os.interfaces.slack.builders import response_blocks

        original = [
            {
                "type": "card",
                "block_id": "rowact:r1:confirmation:selected:deny",
                "title": {"type": "mrkdwn", "text": "*delete_file*"},
                "actions": [],
            }
        ]
        result = response_blocks(original, {}, [])
        assert result[0]["title"]["text"] == "*Denied:* delete_file"

    def test_skips_actions_blocks(self):
        from agno.os.interfaces.slack.builders import response_blocks

        original = [
            {"type": "card", "block_id": "x", "actions": []},
            {"type": "actions", "block_id": "pause:A1"},
        ]
        result = response_blocks(original, {}, [])
        assert len(result) == 1
        assert result[0]["type"] == "card"

    def test_skips_reject_reason_inputs(self):
        from agno.os.interfaces.slack.builders import response_blocks

        original = [
            {"type": "input", "block_id": "reject_reason:r1"},
            {"type": "card", "block_id": "x", "actions": []},
        ]
        result = response_blocks(original, {}, [])
        assert len(result) == 1
        assert result[0]["type"] == "card"

    def test_builds_submitted_card_from_input_values(self):
        from agno.os.interfaces.slack.builders import response_blocks

        original = [
            {
                "type": "input",
                "block_id": "row:r1:user_input:field1",
                "label": {"type": "plain_text", "text": "Email"},
                "element": {"type": "plain_text_input", "action_id": "input_field:field1"},
            }
        ]
        state_values = {
            "row:r1:user_input:field1": {
                "input_field:field1": {"type": "plain_text_input", "value": "test@example.com"}
            }
        }
        result = response_blocks(original, state_values, [])
        submitted_card = result[-1]
        assert submitted_card["type"] == "card"
        assert submitted_card["title"]["text"] == "*Submitted*"
        assert "Email" in submitted_card["body"]["text"]
        assert "test@example.com" in submitted_card["body"]["text"]

    def test_truncates_body_over_200_chars(self):
        from agno.os.interfaces.slack.builders import response_blocks

        original = [
            {
                "type": "input",
                "block_id": "row:r1:user_input:field1",
                "label": {"type": "plain_text", "text": "Data"},
                "element": {"type": "plain_text_input", "action_id": "input_field:field1"},
            }
        ]
        state_values = {
            "row:r1:user_input:field1": {"input_field:field1": {"type": "plain_text_input", "value": "x" * 300}}
        }
        result = response_blocks(original, state_values, [])
        submitted_card = result[-1]
        assert len(submitted_card["body"]["text"]) <= 200
        assert submitted_card["body"]["text"].endswith("...")
