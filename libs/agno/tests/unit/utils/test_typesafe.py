"""Tests for the SDK-free TypeSafe (Jev) helpers. None of these need `typesafe_sdk`."""

import json
from enum import Enum, IntEnum
from typing import List, Literal, Optional

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.message import Message
from agno.run.base import RunContext
from agno.session.team import TeamSession
from agno.team import Team, TeamMode
from agno.tools.function import Function
from agno.utils.typesafe import (
    GUARDRAIL_PRESETS,
    NONE_OPTION,
    TOOL_QUESTION_ID,
    JevConfigError,
    answers_to_dict,
    answers_to_values,
    choice_question,
    decode_tool_call,
    has_tool_round,
    lowest_confidence,
    messages_to_state,
    parse_team_prompt,
    request_text,
    resolve_member_id,
    route_question,
    schema_to_questions,
    score_question,
    tools_to_questions,
)

# ---------------------------------------------------------------------------
# Question builders
# ---------------------------------------------------------------------------


def test_choice_question_rejects_too_many_options():
    with pytest.raises(JevConfigError, match="at most 255"):
        choice_question("Which?", {str(i): None for i in range(256)})


def test_score_question_level_bounds():
    with pytest.raises(JevConfigError, match="2 to 10 levels"):
        score_question("How much?", ["only one"])
    with pytest.raises(JevConfigError, match="2 to 10 levels"):
        score_question("How much?", [str(i) for i in range(11)])


def test_answers_to_dict_is_json_safe():
    class FakeAnswer:
        def model_dump(self, mode="python"):
            # Score answers key their legend by level number
            return {"type": "score", "score": 1.2, "legend": {0: "low", 1: "high"}, "confidence": 0.9}

    plain = answers_to_dict({"urgency": FakeAnswer(), "flag": {"type": "noul", "noul": 0.7}})
    assert plain["urgency"]["legend"] == {"0": "low", "1": "high"}
    assert json.loads(json.dumps(plain)) == plain


def test_lowest_confidence_ignores_nouls():
    answers = {"a": {"confidence": 0.9}, "b": {"confidence": 0.4}, "c": {"noul": 0.1}}
    assert lowest_confidence(answers) == 0.4
    assert lowest_confidence(answers, ["a", "c"]) == 0.9
    assert lowest_confidence({"c": {"noul": 0.1}}) is None


# ---------------------------------------------------------------------------
# Schema -> questions -> values
# ---------------------------------------------------------------------------


class Department(str, Enum):
    billing = "billing"
    technical = "technical"


class Severity(IntEnum):
    low = 0
    medium = 1
    high = 2


class Customer(BaseModel):
    is_vip: bool = Field(description="Is the customer described as a VIP?")


class Triage(BaseModel):
    department: Department = Field(
        description="Which team should handle this?",
        json_schema_extra={"criteria": {"billing": "Payments and refunds", "technical": "Bugs and outages"}},
    )
    tone: Optional[Literal["calm", "angry"]] = Field(default=None, description="What is the customer's tone?")
    is_urgent: bool = Field(description="Does the message convey urgency?", json_schema_extra={"threshold": 0.8})
    severity: Severity = Field(description="How severe is the problem?")
    effort: int = Field(
        description="How much work is this?", json_schema_extra={"criteria": ["minutes", "hours", "days"]}
    )
    topics: List[Literal["refund", "login"]] = Field(default_factory=list, description="Is the ticket about {}?")
    customer: Customer
    summary: str = "not answered by Jev"


def test_schema_to_questions_maps_each_field_kind():
    plan = schema_to_questions(Triage)
    questions = plan.questions

    assert questions["department"]["type"] == "choice"
    assert questions["department"]["criteria"] == {"billing": "Payments and refunds", "technical": "Bugs and outages"}
    # An Optional closed set gains a way to say nothing fits
    assert set(questions["tone"]["criteria"]) == {"calm", "angry", NONE_OPTION}
    assert questions["is_urgent"] == {"type": "noul", "instructions": "Does the message convey urgency?"}
    assert questions["severity"]["type"] == "score"
    assert questions["severity"]["criteria"] == ["low", "medium", "high"]
    assert questions["effort"]["criteria"] == ["minutes", "hours", "days"]
    # One noul per value, with the value filled into the question
    assert questions["topics.refund"]["instructions"] == "Is the ticket about refund?"
    assert questions["topics.login"]["type"] == "noul"
    # Nested models use dotted ids; free text with a default is skipped
    assert "customer.is_vip" in questions
    assert "summary" not in questions


def test_answers_to_values_round_trips_into_the_model():
    plan = schema_to_questions(Triage)
    answers = {
        "department": {"choice": "technical", "confidence": 0.9},
        "tone": {"choice": NONE_OPTION, "confidence": 0.6},
        "is_urgent": {"noul": 0.75},
        "severity": {"score": 1.6, "confidence": 0.8},
        "effort": {"score": 0.4, "confidence": 0.8},
        "topics.refund": {"noul": 0.9},
        "topics.login": {"noul": 0.1},
        "customer.is_vip": {"noul": 0.99},
    }
    triage = Triage.model_validate(answers_to_values(answers, plan))

    assert triage.department is Department.technical
    assert triage.tone is None
    # 0.75 is under this field's own 0.8 threshold
    assert triage.is_urgent is False
    assert triage.severity is Severity.high
    assert triage.effort == 0
    assert triage.topics == ["refund"]
    assert triage.customer.is_vip is True
    assert triage.summary == "not answered by Jev"


def test_score_decoding_clamps_to_the_known_levels():
    plan = schema_to_questions(Triage)
    answers = {
        "department": {"choice": "billing"},
        "tone": {"choice": "calm"},
        "is_urgent": {"noul": 0.9},
        "severity": {"score": 7.0},
        "effort": {"score": 1.0},
        "topics.refund": {"noul": 0.0},
        "topics.login": {"noul": 0.0},
        "customer.is_vip": {"noul": 0.0},
    }
    assert answers_to_values(answers, plan)["severity"] is Severity.high


def test_required_free_text_field_is_rejected():
    class NeedsText(BaseModel):
        reply: str = Field(description="Write a reply")

    with pytest.raises(JevConfigError, match="'reply'"):
        schema_to_questions(NeedsText)


def test_schema_without_any_answerable_field_is_rejected():
    class OnlyText(BaseModel):
        reply: str = "x"

    with pytest.raises(JevConfigError, match="no field Jev can answer"):
        schema_to_questions(OnlyText)


def test_missing_answer_is_reported():
    plan = schema_to_questions(Customer)
    with pytest.raises(ValueError, match="no answer"):
        answers_to_values({}, plan)


# ---------------------------------------------------------------------------
# Closed-set tool calling
# ---------------------------------------------------------------------------


def plot_price(
    symbol: Literal["SPY", "NVDA"],
    style: Literal["line", "candles"] = "line",
    include_volume: bool = False,
    overlays: Optional[List[Literal["sma", "ema"]]] = None,
    limit: int = 3,
) -> str:
    """Plot a price chart.

    Args:
        symbol: the ticker to plot
        style: how the chart is drawn
        include_volume: whether to add volume bars
        overlays: indicators drawn over the price
        limit: how many bars
    """
    return "chart"


def list_symbols() -> str:
    """List the tickers that are available."""
    return "SPY, NVDA"


def search(query: str) -> str:
    """Search the web."""
    return query


def _tool_dicts(*callables):
    return [{"type": "function", "function": Function.from_callable(c).to_dict()} for c in callables]


def test_tools_to_questions_builds_one_fan_out_request():
    plan = tools_to_questions(_tool_dicts(plot_price, list_symbols))
    questions = plan.questions

    assert set(questions[TOOL_QUESTION_ID]["criteria"]) == {"plot_price", "list_symbols", NONE_OPTION}
    assert questions["plot_price.symbol"]["type"] == "choice"
    # Required arguments are always filled, optional ones only when the request states them
    assert "plot_price.symbol?" not in questions
    assert questions["plot_price.style?"]["type"] == "noul"
    assert questions["plot_price.include_volume"]["type"] == "noul"
    assert {"plot_price.overlays.sma", "plot_price.overlays.ema"} <= set(questions)
    # A number with a default cannot be filled and is simply left to its default
    assert not any(q.startswith("plot_price.limit") for q in questions)


def test_decode_tool_call_reads_only_the_chosen_tool():
    plan = tools_to_questions(_tool_dicts(plot_price, list_symbols))
    answers = {
        TOOL_QUESTION_ID: {"choice": "plot_price", "confidence": 0.9},
        "plot_price.symbol": {"choice": "NVDA", "confidence": 0.8},
        "plot_price.style": {"choice": "candles", "confidence": 0.7},
        "plot_price.style?": {"noul": 0.9},
        "plot_price.include_volume": {"noul": 0.9},
        "plot_price.include_volume?": {"noul": 0.1},
        "plot_price.overlays.sma": {"noul": 0.9},
        "plot_price.overlays.ema": {"noul": 0.2},
        "plot_price.overlays?": {"noul": 0.8},
    }
    name, arguments, read = decode_tool_call(answers, plan)

    assert name == "plot_price"
    # include_volume was not stated, so the function default stands
    assert arguments == {"symbol": "NVDA", "style": "candles", "overlays": ["sma"]}
    assert "plot_price.include_volume" not in read
    assert lowest_confidence(answers, read) == 0.7


def test_decode_tool_call_none_option():
    plan = tools_to_questions(_tool_dicts(list_symbols))
    name, arguments, _ = decode_tool_call({TOOL_QUESTION_ID: {"choice": NONE_OPTION, "confidence": 0.9}}, plan)
    assert name is None and arguments == {}


def test_required_open_argument_is_rejected():
    with pytest.raises(JevConfigError, match="required argument 'query'"):
        tools_to_questions(_tool_dicts(search))


def test_forced_tool_choice_skips_the_tool_question():
    plan = tools_to_questions(
        _tool_dicts(plot_price, list_symbols), tool_choice={"type": "function", "name": "plot_price"}
    )
    assert plan.forced_tool == "plot_price"
    assert TOOL_QUESTION_ID not in plan.questions


def test_required_tool_choice_drops_the_none_option():
    plan = tools_to_questions(_tool_dicts(plot_price, list_symbols), tool_choice="required")
    assert NONE_OPTION not in plan.questions[TOOL_QUESTION_ID]["criteria"]


def test_strict_schema_open_arguments_are_left_out():
    tool = _tool_dicts(search)[0]
    tool["function"]["strict"] = True
    plan = tools_to_questions([tool])
    assert plan.tools["search"] == []


# ---------------------------------------------------------------------------
# Team leader prompt, parsed from prompts a real Team renders
# ---------------------------------------------------------------------------


def _leader_prompt(mode: TeamMode, **team_kwargs) -> str:
    # No model on purpose: rendering the prompt needs none, and nothing here should reach a provider
    billing = Agent(
        name="Billing Agent",
        id="billing",
        role="Handles charges,\nrefunds and invoices",
        description='Knows <Stripe> & the "refund policy"',
    )
    tech = Agent(name="Tech Support", role="Bugs and outages")
    research = Team(
        name="Research Squad", id="research", role="Deep research", members=[Agent(name="Searcher", role="web")]
    )
    team = Team(
        name="Support",
        mode=mode,
        members=[billing, tech, research],
        description="You are the support desk.",
        instructions=["Send anything about money to billing.", "Outages go to tech."],
        **team_kwargs,
    )
    team.initialize_team()
    message = team.get_system_message(
        session=TeamSession(session_id="s"), run_context=RunContext(run_id="r", session_id="s")
    )
    assert message is not None
    return str(message.content)


@pytest.mark.parametrize(
    "mode, expected",
    [
        (TeamMode.route, "route"),
        (TeamMode.broadcast, "broadcast"),
        (TeamMode.coordinate, "coordinate"),
        (TeamMode.tasks, "tasks"),
    ],
)
def test_parse_team_prompt_reads_the_mode(mode, expected):
    assert parse_team_prompt(_leader_prompt(mode)).mode == expected


def test_parse_team_prompt_reads_the_roster():
    parsed = parse_team_prompt(_leader_prompt(TeamMode.route))

    assert [m.id for m in parsed.members] == ["billing", "tech-support", "research"]
    billing, tech, research = parsed.members
    assert billing.name == "Billing Agent"
    # Values are rendered verbatim: multi-line and unescaped
    assert billing.role == "Handles charges,\nrefunds and invoices"
    assert billing.description == 'Knows <Stripe> & the "refund policy"'
    assert tech.description is None
    # A sub-team is one delegable member; its own members are context, not targets
    assert research.is_team is True
    assert research.role == "Deep research"
    assert research.members == ["Searcher"]


def test_parse_team_prompt_reads_member_tools():
    def lookup_invoice(invoice_id: str) -> str:
        """Look up an invoice."""
        return invoice_id

    team = Team(
        name="Support",
        mode=TeamMode.route,
        add_member_tools_to_context=True,
        members=[Agent(name="Billing Agent", id="billing", role="Invoices", tools=[lookup_invoice])],
    )
    team.initialize_team()
    message = team.get_system_message(
        session=TeamSession(session_id="s"), run_context=RunContext(run_id="r", session_id="s")
    )
    assert message is not None
    parsed = parse_team_prompt(str(message.content))
    assert parsed.members[0].tools == "lookup_invoice"
    assert parsed.members[0].to_criteria() == {"name": "Billing Agent", "role": "Invoices", "tools": "lookup_invoice"}


def test_parse_team_prompt_reads_the_developer_guidance():
    guidance = parse_team_prompt(_leader_prompt(TeamMode.route)).guidance
    assert "You are the support desk." in guidance
    assert "Send anything about money to billing." in guidance
    # Wrapper tags and the framework's own team block are not guidance
    assert "<description>" not in guidance
    assert "You coordinate this team" not in guidance


def test_parse_team_prompt_without_a_roster():
    parsed = parse_team_prompt("You are a helpful assistant.")
    assert parsed.mode is None and parsed.members == [] and parsed.guidance == ""
    assert parse_team_prompt(None).members == []


def test_route_question_uses_member_ids_as_options():
    parsed = parse_team_prompt(_leader_prompt(TeamMode.route))
    question = route_question(parsed.members, parsed.guidance)

    assert question["type"] == "choice"
    assert list(question["criteria"]) == ["billing", "tech-support", "research"]
    assert question["criteria"]["tech-support"] == {"name": "Tech Support", "role": "Bugs and outages"}
    assert "Outages go to tech." in question["instructions"]["guidance"]


def test_resolve_member_id_accepts_id_or_name():
    members = parse_team_prompt(_leader_prompt(TeamMode.route)).members
    assert resolve_member_id(members, "billing") == "billing"
    assert resolve_member_id(members, "Tech Support") == "tech-support"
    assert resolve_member_id(members, "nobody") is None


# ---------------------------------------------------------------------------
# Messages -> state
# ---------------------------------------------------------------------------


def test_messages_to_state_separates_request_history_and_context():
    messages = [
        Message(role="system", content="Refunds are allowed within 30 days."),
        Message(role="user", content="Hi", from_history=True),
        Message(role="assistant", content="Hello, how can I help?", from_history=True),
        Message(role="user", content="I want my money back."),
    ]
    assert messages_to_state(messages) == {
        "request": "I want my money back.",
        "conversation": [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello, how can I help?"},
        ],
        "context": "Refunds are allowed within 30 days.",
    }
    assert "context" not in messages_to_state(messages, include_system=False)


def test_messages_to_state_includes_tool_results():
    messages = [
        Message(role="user", content="What tickers do you have?"),
        Message(role="assistant", tool_calls=[{"id": "1", "type": "function"}]),
        Message(role="tool", content="SPY, NVDA", tool_name="list_symbols", tool_call_id="1"),
    ]
    assert has_tool_round(messages) is True
    assert messages_to_state(messages)["results"] == [{"tool": "list_symbols", "result": "SPY, NVDA"}]


def test_tool_rounds_from_history_do_not_count():
    messages = [
        Message(role="assistant", tool_calls=[{"id": "1", "type": "function"}], from_history=True),
        Message(role="user", content="And now?"),
    ]
    assert has_tool_round(messages) is False


def test_request_text_needs_a_user_message():
    with pytest.raises(JevConfigError, match="user message"):
        request_text([Message(role="system", content="x")])


# ---------------------------------------------------------------------------
# Guardrail presets
# ---------------------------------------------------------------------------


def test_guardrail_presets_are_well_formed_nouls():
    from agno.exceptions import CheckTrigger

    for name, preset in GUARDRAIL_PRESETS.items():
        assert hasattr(CheckTrigger, preset["trigger"]), name
        for side in ("input", "output"):
            assert preset[side]["type"] == "noul"
            assert set(preset[side]["criteria"]) == {"true", "false"}
