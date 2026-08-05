"""Unit tests for agno.run.requirement — RunRequirement serialization round-trips."""

from agno.models.response import ToolExecution, UserInputField
from agno.run.requirement import RunRequirement

# =============================================================================
# Helpers
# =============================================================================


def build_confirmation_requirement_dict(**overrides) -> dict:
    """A stored requirement dict for a tool call awaiting confirmation."""
    data = {
        "id": "req-1",
        "tool_execution": {
            "tool_name": "delete_file",
            "tool_args": {"path": "/tmp/x"},
            "tool_call_id": "call-1",
            "requires_confirmation": True,
        },
    }
    data.update(overrides)
    return data


def build_input_field_dict(name: str, value=None) -> dict:
    return {"name": name, "field_type": "str", "description": None, "value": value}


def build_user_input_requirement_dict(top_values: dict, nested_values: dict) -> dict:
    """A stored requirement dict for a tool call awaiting user input.

    Carries the schema twice — requirement level and inside tool_execution —
    exactly as to_dict() ships it over the wire.
    """
    return {
        "id": "req-input",
        "tool_execution": {
            "tool_name": "send_email",
            "tool_args": {},
            "tool_call_id": "call-input",
            "requires_user_input": True,
            "user_input_schema": [build_input_field_dict(name, value) for name, value in nested_values.items()],
        },
        "user_input_schema": [build_input_field_dict(name, value) for name, value in top_values.items()],
    }


def build_feedback_question_dict(question: str, labels: list, selected_options=None) -> dict:
    return {
        "question": question,
        "header": None,
        "multi_select": False,
        "selected_options": selected_options,
        "options": [{"label": label, "description": None, "selected": False} for label in labels],
    }


def build_user_feedback_requirement_dict(top_questions: list, nested_questions: list) -> dict:
    """A stored requirement dict for an ask_user tool call awaiting feedback."""
    return {
        "id": "req-feedback",
        "tool_execution": {
            "tool_name": "ask_user",
            "tool_args": {},
            "tool_call_id": "call-feedback",
            "requires_user_input": True,
            "user_feedback_schema": nested_questions,
        },
        "user_feedback_schema": top_questions,
    }


# =============================================================================
# from_dict: top-level confirmation propagates to tool_execution
# =============================================================================


class TestFromDictConfirmationPropagation:
    def test_top_level_confirmation_true_reaches_tool_execution(self):
        """A bare top-level {"confirmation": true} must set tool_execution.confirmed."""
        req = RunRequirement.from_dict(build_confirmation_requirement_dict(confirmation=True))
        assert req.confirmation is True
        assert req.tool_execution is not None
        assert req.tool_execution.confirmed is True
        assert req.needs_confirmation is False

    def test_top_level_rejection_propagates_note(self):
        req = RunRequirement.from_dict(build_confirmation_requirement_dict(confirmation=False, confirmation_note="no"))
        assert req.confirmation is False
        assert req.tool_execution is not None
        assert req.tool_execution.confirmed is False
        assert req.tool_execution.confirmation_note == "no"

    def test_nested_confirmed_stays_authoritative(self):
        """An explicitly set tool_execution.confirmed wins over the top-level field."""
        data = build_confirmation_requirement_dict(confirmation=True)
        data["tool_execution"]["confirmed"] = False
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.confirmed is False

    def test_no_confirmation_leaves_tool_execution_untouched(self):
        req = RunRequirement.from_dict(build_confirmation_requirement_dict())
        assert req.confirmation is None
        assert req.tool_execution is not None
        assert req.tool_execution.confirmed is None
        assert req.needs_confirmation is True

    def test_round_trip_preserves_confirm(self):
        requirement = RunRequirement(
            tool_execution=ToolExecution(
                tool_name="delete_file",
                tool_args={"path": "/tmp/x"},
                tool_call_id="call-1",
                requires_confirmation=True,
            )
        )
        requirement.confirm()
        restored = RunRequirement.from_dict(requirement.to_dict())
        assert restored.confirmation is True
        assert restored.tool_execution is not None
        assert restored.tool_execution.confirmed is True
        assert restored.needs_confirmation is False


# =============================================================================
# from_dict: external_execution_result propagates to tool_execution
# =============================================================================


class TestFromDictExternalExecutionResultPropagation:
    def test_top_level_result_reaches_tool_execution(self):
        data = {
            "id": "req-2",
            "tool_execution": {
                "tool_name": "run_query",
                "tool_args": {"sql": "select 1"},
                "tool_call_id": "call-2",
                "external_execution_required": True,
            },
            "external_execution_result": "1 row",
        }
        req = RunRequirement.from_dict(data)
        assert req.external_execution_result == "1 row"
        assert req.tool_execution is not None
        assert req.tool_execution.result == "1 row"
        assert req.needs_external_execution is False

    def test_nested_result_stays_authoritative(self):
        data = {
            "id": "req-3",
            "tool_execution": {
                "tool_name": "run_query",
                "tool_args": {"sql": "select 1"},
                "tool_call_id": "call-3",
                "external_execution_required": True,
                "result": "nested result",
            },
            "external_execution_result": "top-level result",
        }
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.result == "nested result"


# =============================================================================
# from_dict: user_input_schema values propagate to tool_execution
# =============================================================================


class TestFromDictUserInputSchemaPropagation:
    def test_top_level_values_reach_tool_execution(self):
        """Values filled on the requirement-level schema copy must reach tool_execution."""
        data = build_user_input_requirement_dict(
            top_values={"to": "a@b.com", "body": "hello"},
            nested_values={"to": None, "body": None},
        )
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.user_input_schema is not None
        nested = {f.name: f.value for f in req.tool_execution.user_input_schema}
        assert nested == {"to": "a@b.com", "body": "hello"}
        assert req.tool_execution.answered is True
        assert req.needs_user_input is False

    def test_partial_fill_does_not_mark_answered(self):
        data = build_user_input_requirement_dict(
            top_values={"to": "a@b.com", "body": None},
            nested_values={"to": None, "body": None},
        )
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.user_input_schema is not None
        nested = {f.name: f.value for f in req.tool_execution.user_input_schema}
        assert nested == {"to": "a@b.com", "body": None}
        assert req.tool_execution.answered is None
        assert req.needs_user_input is True

    def test_nested_value_stays_authoritative(self):
        data = build_user_input_requirement_dict(
            top_values={"to": "other@x.com"},
            nested_values={"to": "ops@x.com"},
        )
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.user_input_schema is not None
        assert req.tool_execution.user_input_schema[0].value == "ops@x.com"

    def test_prefilled_pause_reload_stays_unanswered(self):
        """A stored pause can carry model-prefilled values in both copies; reloading it must not read as answered."""
        data = build_user_input_requirement_dict(
            top_values={"to": "model@guess.com", "body": "model draft"},
            nested_values={"to": "model@guess.com", "body": "model draft"},
        )
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.answered is None
        assert req.needs_user_input is True

    def test_missing_nested_schema_gets_requirement_copy(self):
        data = build_user_input_requirement_dict(top_values={"to": "a@b.com"}, nested_values={})
        del data["tool_execution"]["user_input_schema"]
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.user_input_schema is req.user_input_schema
        assert req.tool_execution.answered is None

    def test_round_trip_preserves_provide_user_input(self):
        requirement = RunRequirement(
            tool_execution=ToolExecution(
                tool_name="send_email",
                tool_args={},
                tool_call_id="call-input",
                requires_user_input=True,
                user_input_schema=[
                    UserInputField(name="to", field_type=str),
                    UserInputField(name="body", field_type=str),
                ],
            )
        )
        requirement.provide_user_input({"to": "a@b.com", "body": "hello"})
        restored = RunRequirement.from_dict(requirement.to_dict())
        assert restored.tool_execution is not None
        assert restored.tool_execution.user_input_schema is not None
        nested = {f.name: f.value for f in restored.tool_execution.user_input_schema}
        assert nested == {"to": "a@b.com", "body": "hello"}
        assert restored.tool_execution.answered is True
        assert restored.needs_user_input is False


# =============================================================================
# from_dict: user_feedback_schema selections propagate to tool_execution
# =============================================================================


class TestFromDictUserFeedbackSchemaPropagation:
    def test_top_level_selections_reach_tool_execution(self):
        data = build_user_feedback_requirement_dict(
            top_questions=[build_feedback_question_dict("Ship it?", ["yes", "no"], selected_options=["yes"])],
            nested_questions=[build_feedback_question_dict("Ship it?", ["yes", "no"])],
        )
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.user_feedback_schema is not None
        question = req.tool_execution.user_feedback_schema[0]
        assert question.selected_options == ["yes"]
        assert question.options is not None
        assert {opt.label: opt.selected for opt in question.options} == {"yes": True, "no": False}
        assert req.tool_execution.answered is True
        assert req.needs_user_feedback is False

    def test_nested_selections_stay_authoritative(self):
        data = build_user_feedback_requirement_dict(
            top_questions=[build_feedback_question_dict("Ship it?", ["yes", "no"], selected_options=["yes"])],
            nested_questions=[build_feedback_question_dict("Ship it?", ["yes", "no"], selected_options=["no"])],
        )
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.user_feedback_schema is not None
        assert req.tool_execution.user_feedback_schema[0].selected_options == ["no"]

    def test_partial_selections_do_not_mark_answered(self):
        data = build_user_feedback_requirement_dict(
            top_questions=[
                build_feedback_question_dict("Ship it?", ["yes", "no"], selected_options=["yes"]),
                build_feedback_question_dict("Which env?", ["dev", "prod"]),
            ],
            nested_questions=[
                build_feedback_question_dict("Ship it?", ["yes", "no"]),
                build_feedback_question_dict("Which env?", ["dev", "prod"]),
            ],
        )
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.user_feedback_schema is not None
        assert req.tool_execution.user_feedback_schema[0].selected_options == ["yes"]
        assert req.tool_execution.user_feedback_schema[1].selected_options is None
        assert req.tool_execution.answered is None
        assert req.needs_user_feedback is True
