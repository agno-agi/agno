from typing import TYPE_CHECKING

from agno.eval.base import BaseEval

if TYPE_CHECKING:
    from agno.eval.accuracy import AccuracyAgentResponse, AccuracyEval, AccuracyEvaluation, AccuracyResult
    from agno.eval.agent_as_judge import AgentAsJudgeEval, AgentAsJudgeEvaluation, AgentAsJudgeResult
    from agno.eval.performance import PerformanceEval, PerformanceResult
    from agno.eval.reliability import ReliabilityEval, ReliabilityResult
    from agno.eval.suite import (
        Case,
        CaseResult,
        EvalSuite,
        JudgeMode,
        SuiteResult,
        acli,
        arun_cases,
        cli,
        run_cases,
    )

__all__ = [
    "AccuracyAgentResponse",
    "AccuracyEvaluation",
    "AccuracyResult",
    "AccuracyEval",
    "AgentAsJudgeEval",
    "AgentAsJudgeEvaluation",
    "AgentAsJudgeResult",
    "BaseEval",
    "Case",
    "CaseResult",
    "EvalSuite",
    "JudgeMode",
    "PerformanceEval",
    "PerformanceResult",
    "ReliabilityEval",
    "ReliabilityResult",
    "SuiteResult",
    "acli",
    "arun_cases",
    "cli",
    "run_cases",
]


def __getattr__(name: str):
    """Lazy import for eval implementations to avoid circular imports with Agent."""
    if name in ("AccuracyAgentResponse", "AccuracyEval", "AccuracyEvaluation", "AccuracyResult"):
        from agno.eval import accuracy

        return getattr(accuracy, name)
    elif name in ("AgentAsJudgeEval", "AgentAsJudgeEvaluation", "AgentAsJudgeResult"):
        from agno.eval import agent_as_judge

        return getattr(agent_as_judge, name)
    elif name in ("PerformanceEval", "PerformanceResult"):
        from agno.eval import performance

        return getattr(performance, name)
    elif name in ("ReliabilityEval", "ReliabilityResult"):
        from agno.eval import reliability

        return getattr(reliability, name)
    elif name in (
        "Case",
        "CaseResult",
        "EvalSuite",
        "JudgeMode",
        "SuiteResult",
        "arun_cases",
        "run_cases",
        "cli",
        "acli",
    ):
        from agno.eval import suite

        return getattr(suite, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
