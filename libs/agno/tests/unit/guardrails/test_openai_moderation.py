"""Unit tests for OpenAIModerationGuardrail category matching (mocked client)."""

from unittest.mock import MagicMock, patch

import pytest
from openai.types.moderation import Categories, CategoryScores

from agno.exceptions import InputCheckError
from agno.guardrails.openai import OpenAIModerationGuardrail
from agno.run.agent import RunInput

# Categories whose OpenAI names carry a "/" or "-" alias (distinct from the
# underscore field name). raise_for_categories and OpenAI's docs use these.
ALIASED_CATEGORIES = [
    "sexual/minors",
    "harassment/threatening",
    "hate/threatening",
    "illicit/violent",
    "self-harm",
    "self-harm/intent",
    "self-harm/instructions",
    "violence/graphic",
]
PLAIN_CATEGORIES = ["harassment", "hate", "illicit", "sexual", "violence"]


def _flagged_response(flagged_category: str) -> MagicMock:
    cat_aliases = [f.alias or n for n, f in Categories.model_fields.items()]
    categories = Categories.model_validate({a: (a == flagged_category) for a in cat_aliases})
    score_aliases = [f.alias or n for n, f in CategoryScores.model_fields.items()]
    scores = CategoryScores.model_validate(
        {a: (0.9 if a == flagged_category else 0.0) for a in score_aliases}
    )
    result = MagicMock()
    result.flagged = True
    result.categories = categories
    result.category_scores = scores
    response = MagicMock()
    response.results = [result]
    return response


@pytest.mark.parametrize("category", ALIASED_CATEGORIES + PLAIN_CATEGORIES)
def test_check_raises_for_flagged_category(category):
    """A flagged category listed in raise_for_categories must raise InputCheckError.

    Regression: the categories dict was built with ``model_dump()`` (underscore
    keys) while ``raise_for_categories`` uses the slash/hyphen aliases, so the
    lookup raised KeyError for the 8 aliased categories instead of blocking.
    """
    guardrail = OpenAIModerationGuardrail(raise_for_categories=[category], api_key="test")
    with patch("openai.OpenAI") as mock_client:
        mock_client.return_value.moderations.create.return_value = _flagged_response(category)
        with pytest.raises(InputCheckError):
            guardrail.check(RunInput(input_content="bad content"))


def test_check_does_not_raise_for_unlisted_category():
    """A category that is flagged but NOT in raise_for_categories does not trigger."""
    guardrail = OpenAIModerationGuardrail(raise_for_categories=["violence"], api_key="test")
    with patch("openai.OpenAI") as mock_client:
        mock_client.return_value.moderations.create.return_value = _flagged_response("self-harm/intent")
        guardrail.check(RunInput(input_content="content"))  # no raise
