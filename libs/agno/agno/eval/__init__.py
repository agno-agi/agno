from agno.eval.base import BaseEval

__all__ = [
    "AccuracyAgentResponse",
    "AccuracyEvaluation",
    "AccuracyResult",
    "AccuracyEval",
    "AgentAsJudgeEval",
    "AgentAsJudgeEvaluation",
    "AgentAsJudgeResult",
    "BaseEval",
    "PerformanceEval",
    "PerformanceResult",
    "ReliabilityEval",
    "ReliabilityResult",
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
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
