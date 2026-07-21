"""JudgeScorer: score runs with an LLM judge against free-text criteria."""

import hashlib
import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.base import Model
from agno.scorer._fence import fence_untrusted
from agno.scorer._model import model_identity_payload, model_prompt_payload
from agno.scorer.base import AnyRunOutput, FingerprintError, Score


# Local schema: agno.scorer must not import agno.eval.
class NumericJudgeResponse(BaseModel):
    """Response schema for numeric scoring mode."""

    score: int = Field(..., ge=1, le=10, description="Score between 1 and 10.")
    reason: str = Field(..., description="Detailed reasoning for the evaluation.")


class BinaryJudgeResponse(BaseModel):
    """Response schema for binary scoring mode."""

    passed: bool = Field(..., description="Pass/fail result.")
    reason: str = Field(..., description="Detailed reasoning for the evaluation.")


_NUMERIC_INSTRUCTIONS = [
    "## Scoring (1-10)",
    "- 1-2: Completely fails the criteria",
    "- 3-4: Major issues",
    "- 5-6: Partial success with significant issues",
    "- 7-8: Mostly meets criteria with minor issues",
    "- 9-10: Fully meets or exceeds criteria",
    "",
    "## Instructions",
    "1. Carefully evaluate the output against the criteria above",
    "2. Provide a score from 1-10",
    "3. Provide detailed reasoning that references specific parts of the output",
]

_BINARY_INSTRUCTIONS = [
    "## Evaluation",
    "Determine if the output PASSES or FAILS the criteria above.",
    "",
    "## Instructions",
    "1. Carefully evaluate the output against the criteria above",
    "2. Decide if it passes (true) or fails (false)",
    "3. Provide detailed reasoning that references specific parts of the output",
]


def _build_judge_prompt(
    criteria: str,
    mode: str,
    output_text: str,
    input_text: Optional[str],
    expected: Any,
) -> str:
    """One prompt carrying criteria, instructions, and the fenced untrusted texts.

    Everything lives in the prompt, never in agent instructions: the fence must also
    hold when the judged text reaches a judge the caller configured themselves.
    """
    parts = ["## Criteria", criteria, ""]
    parts.extend(_NUMERIC_INSTRUCTIONS if mode == "numeric" else _BINARY_INSTRUCTIONS)
    if input_text:
        parts.extend(["", "<input>", input_text, "</input>"])
    if expected is not None:
        # A reference answer loaded from a dataset is data, not instructions.
        parts.extend(
            ["", "A reference answer follows for comparison.", fence_untrusted(str(expected), label="expected")]
        )
    parts.extend(["", fence_untrusted(output_text, label="output")])
    return "\n".join(parts)


class JudgeScorer:
    """Run an LLM judge over a run's output.

    `model` is required, so the judge model is always a visible choice. `threshold`
    is on the raw 1-10 scale (matching `AgentAsJudgeEval.threshold`)
    and is read only in numeric mode: `passed = raw_score >= threshold`. Numeric mode
    normalizes `value = (score - 1) / 9` for exact endpoints -- judge 1 -> 0.0,
    judge 10 -> 1.0. The raw score lands in `Score.detail["raw_score"]`.
    """

    def __init__(
        self,
        model: Model,
        criteria: str,
        *,
        mode: Literal["binary", "numeric"] = "binary",
        threshold: int = 7,
    ) -> None:
        if mode not in ("binary", "numeric"):
            raise ValueError(f"mode must be 'binary' or 'numeric', got {mode!r}")
        if mode == "numeric" and not 1 <= threshold <= 10:
            raise ValueError(f"threshold must be between 1 and 10, got {threshold}")
        self.model = model
        self.criteria = criteria
        self.mode = mode
        self.threshold = threshold
        # One evaluator agent per scorer, reused across attempts.
        self._evaluator = Agent(
            model=model,
            description="You are an expert evaluator. Score outputs objectively based on the provided criteria.",
            output_schema=NumericJudgeResponse if mode == "numeric" else BinaryJudgeResponse,
        )

    def _prompt_for(self, run: AnyRunOutput, expected: Any) -> str:
        # The same extraction the eval suite uses for evidence, with the same fallback:
        # get_content_as_string raises on values json cannot handle.
        try:
            output_text = run.get_content_as_string() if run.content is not None else ""
        except Exception:
            output_text = str(run.content)
        input_text = run.input.input_content_string() if run.input is not None else None
        return _build_judge_prompt(self.criteria, self.mode, output_text, input_text, expected)

    def _to_score(self, content: Any) -> Score:
        if self.mode == "numeric":
            if not isinstance(content, NumericJudgeResponse):
                raise ValueError(f"judge returned an invalid response: {content!r}")
            return Score(
                value=(content.score - 1) / 9,
                passed=content.score >= self.threshold,
                reason=content.reason,
                detail={"raw_score": content.score},
            )
        if not isinstance(content, BinaryJudgeResponse):
            raise ValueError(f"judge returned an invalid response: {content!r}")
        return Score(value=1.0 if content.passed else 0.0, passed=content.passed, reason=content.reason)

    def score(self, run: AnyRunOutput, expected: Any = None) -> Score:
        response = self._evaluator.run(self._prompt_for(run, expected), stream=False)
        return self._to_score(response.content)

    async def ascore(self, run: AnyRunOutput, expected: Any = None) -> Score:
        response = await self._evaluator.arun(self._prompt_for(run, expected), stream=False)
        return self._to_score(response.content)

    def digest(self) -> str:
        """sha256 hex over criteria, mode, threshold and the judge model's identity.

        The judge is part of the scoring rule: swapping it -- by id, provider,
        base_url, sampling params, or a model-level prompt, not just id -- is an
        environment change, so the model contributes the same identity payload the
        policy fingerprint uses, plus its prompt-shaped fields (which the policy
        payload deliberately excludes -- for the judge they shape the verdict).
        """
        payload = {
            "criteria": self.criteria,
            "mode": self.mode,
            "threshold": self.threshold,
            "model": model_identity_payload(self.model),
            "model_prompt": model_prompt_payload(self.model),
        }
        try:
            canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise FingerprintError(f"JudgeScorer identity is not JSON-serializable: {exc}") from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
