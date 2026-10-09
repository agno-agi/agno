import os

import pytest

pytest.importorskip("openai.resources.decisions", reason="requires openai>=3.26.0, the first release with Decisions")

from agno.models.decision import Choice, Noul, Score
from agno.models.openai import OpenAIDecisions

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")

QUESTIONS = {
    "urgent": Noul(instructions="Does the customer need this resolved today?"),
    "area": Choice(instructions="Which team owns this ticket?", options=["billing", "technical", "sales"]),
    "severity": Score(instructions="How badly is the product affected?", levels=["Cosmetic", "Degraded", "Outage"]),
}

TICKET = "Checkout has returned 500 errors for an hour and our sale launches tomorrow morning."


def _check(result):
    assert set(result) == set(QUESTIONS)
    assert 0 <= result["urgent"].probability <= 1
    assert result["area"].value in {"billing", "technical", "sales"}
    assert abs(sum(result["area"].probabilities.values()) - 1) < 0.05
    assert result["severity"].label in {"Cosmetic", "Degraded", "Outage"}
    assert result.metrics is not None and result.metrics.input_tokens > 0


def test_decide():
    _check(OpenAIDecisions().decide(state=TICKET, questions=QUESTIONS))


async def test_adecide():
    _check(await OpenAIDecisions().adecide(state=TICKET, questions=QUESTIONS))
