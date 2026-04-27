from typing import Any, Dict

from agno.models.response import ToolExecution
from agno.os.interfaces.slack.builders import build_pause_message, classify_requirement
from agno.os.interfaces.slack.parsers import format_decision_title, parse_submit_payload
from agno.os.interfaces.slack.types import (
    ACTION_EXTERNAL_RESULT,
    ACTION_FEEDBACK_SELECT,
    ACTION_INPUT_FIELD_PREFIX,
    ACTION_ROW_APPROVE,
    ACTION_ROW_REJECT,
    ACTION_SUBMIT,
    ParsedDecision,
    parse_row_block_id,
    pause_block_id,
    row_block_id,
)
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


# -- classify_requirement --


class TestClassifyRequirement:
    def test_user_feedback_wins(self):
        # Order mirrors os.agno.com utils.ts: feedback > external > input > confirmation.
        req = _make_requirement(
            user_feedback_schema=[UserFeedbackQuestion(question="?", options=[UserFeedbackOption(label="A")])],
            requires_user_input=True,
            requires_confirmation=True,
        )
        assert classify_requirement(req) == "user_feedback"

    def test_external_execution_wins_over_input_and_confirmation(self):
        req = _make_requirement(
            external_execution_required=True,
            requires_user_input=True,
            requires_confirmation=True,
        )
        assert classify_requirement(req) == "external_execution"

    def test_user_input_wins_over_confirmation(self):
        req = _make_requirement(requires_user_input=True, requires_confirmation=True)
        assert classify_requirement(req) == "user_input"

    def test_defaults_to_confirmation(self):
        req = _make_requirement(requires_confirmation=True)
        assert classify_requirement(req) == "confirmation"

    def test_missing_tool_execution_is_confirmation(self):
        # DB round-trip can drop tool_execution; fallback keeps the run safe.
        req = _make_requirement()
        req.tool_execution = None
        assert classify_requirement(req) == "confirmation"


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
        assert card.title.text == "*Approve: delete_file*"

    def test_card_subtitle_renders_args(self):
        card = build_pause_message("A1", [_make_requirement(tool_name="delete_file", tool_args={"path": "/tmp/x"})])[0]
        assert "path" in card.subtitle.text
        assert "/tmp/x" in card.subtitle.text

    def test_button_action_ids(self):
        card = build_pause_message("A1", [_make_requirement()])[0]
        assert [el.action_id for el in card.actions] == [ACTION_ROW_APPROVE, ACTION_ROW_REJECT]

    def test_button_value_routing(self):
        # _handle_row_click splits on "|" to recover (req_id, run_id, awaiting_ts).
        card = build_pause_message("A1", [_make_requirement()])[0]
        assert card.actions[0].value == "r1|A1|"
        assert card.actions[1].value == "r1|A1|"

    def test_buttons_carry_confirm_dialogs(self):
        card = build_pause_message("A1", [_make_requirement()])[0]
        assert card.actions[0].confirm is not None
        assert card.actions[1].confirm is not None


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

    def test_user_input_bool_coerced(self):
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
        assert decisions[0].input_values == {"force": True}

    def test_user_input_list_parsed_from_json(self):
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
        assert decisions[0].input_values == {"tags": ["a", "b"]}

    def test_user_input_bad_json_records_error(self):
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
        assert len(errors) == 1
        assert errors[0].field == "tags"
        assert decisions[0].input_values == {"tags": None}

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

    def test_confirmation_without_click_defaults_to_rejected(self):
        # Submit with no click — parser treats as rejected so runs stay safe.
        req = _make_requirement(tool_name="delete_file")
        decisions, _ = parse_submit_payload(_submit_payload(), [req])
        assert decisions[0].approved is False
        assert decisions[0].rejected_note == "No decision made"

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


class TestFormatDecisionTitle:
    def test_approved_confirmation_inlines_args(self):
        req = _make_requirement(
            tool_name="cancel_subscription",
            tool_args={"customer_id": "C-42", "reason": "pricing"},
        )
        decision = ParsedDecision(requirement_id="r1", pause_type="confirmation", approved=True)
        assert format_decision_title(decision, req) == "Approved: cancel_subscription(customer_id=C-42, reason=pricing)"

    def test_denied_confirmation_inlines_args(self):
        req = _make_requirement(
            tool_name="cancel_subscription",
            tool_args={"customer_id": "C-42", "reason": "pricing"},
        )
        decision = ParsedDecision(requirement_id="r1", pause_type="confirmation", approved=False)
        assert format_decision_title(decision, req) == "Denied: cancel_subscription(customer_id=C-42, reason=pricing)"

    def test_confirmation_empty_args_no_parens(self):
        req = _make_requirement(tool_name="cancel_subscription", tool_args={})
        decision = ParsedDecision(requirement_id="r1", pause_type="confirmation", approved=True)
        assert format_decision_title(decision, req) == "Approved: cancel_subscription"

    def test_value_over_40_chars_truncates(self):
        req = _make_requirement(
            tool_name="cancel_subscription",
            tool_args={"reason": "a" * 60},
        )
        decision = ParsedDecision(requirement_id="r1", pause_type="confirmation", approved=True)
        result = format_decision_title(decision, req)
        # Long value truncated to 40 chars (39 + ellipsis).
        assert "reason=" in result
        assert "…" in result
        assert "a" * 60 not in result

    def test_title_over_120_chars_truncates(self):
        # Several medium-length args that together exceed the 120-char cap.
        req = _make_requirement(
            tool_name="very_long_tool_name_indeed",
            tool_args={f"arg{i}": "x" * 30 for i in range(5)},
        )
        decision = ParsedDecision(requirement_id="r1", pause_type="confirmation", approved=True)
        result = format_decision_title(decision, req)
        assert len(result) <= 120
        assert result.endswith("…")

    def test_newlines_stripped_from_values(self):
        req = _make_requirement(
            tool_name="run_diagnostic",
            tool_args={"command": "line1\nline2\nline3"},
        )
        decision = ParsedDecision(requirement_id="r1", pause_type="confirmation", approved=True)
        result = format_decision_title(decision, req)
        assert "\n" not in result
