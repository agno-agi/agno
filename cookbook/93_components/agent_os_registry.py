"""
This cookbook demonstrates how to use a registry with the AgentOS app.
"""

from typing import List

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.types import StepInput, StepOutput

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", id="postgres_db")


def sample_tool():
    return "Hello, world!"


# =============================================================================
# CUSTOM STEP EXECUTORS
# Functions that can be used as step executors (instead of agent/team)
# =============================================================================


def transform_content(step_input: StepInput) -> StepOutput:
    """Transform content by adding markers - useful for content processing pipelines."""
    previous_content = step_input.previous_step_content or ""
    transformed = f"[TRANSFORMED] {previous_content} [END]"
    return StepOutput(step_name="TransformContent", content=transformed, success=True)


def summarize_step_outputs(step_input: StepInput) -> StepOutput:
    """Aggregate and summarize outputs from previous steps."""
    outputs = step_input.previous_step_outputs or {}
    summary_parts = []
    for step_name, output in outputs.items():
        content_preview = str(output.content)[:100] if output.content else "No content"
        summary_parts.append(f"- {step_name}: {content_preview}...")

    summary = "Summary of previous steps:\n" + "\n".join(summary_parts)
    return StepOutput(step_name="Summarize", content=summary, success=True)


def validate_input(step_input: StepInput) -> StepOutput:
    """Validate that input meets requirements before proceeding."""
    input_text = step_input.input or ""
    errors = []

    if not input_text:
        errors.append("Input is empty")
    elif len(str(input_text)) < 10:
        errors.append("Input is too short (minimum 10 characters)")

    if errors:
        return StepOutput(
            step_name="ValidateInput",
            content=f"Validation failed: {', '.join(errors)}",
            success=False,
            stop=True,  # Stop workflow on validation failure
        )
    return StepOutput(step_name="ValidateInput", content="Input validated", success=True)


# =============================================================================
# CONDITION EVALUATORS
# Functions that return bool to determine if conditional steps should execute
# =============================================================================


def is_tech_topic(step_input: StepInput) -> bool:
    """Check if the topic is technology-related."""
    topic = step_input.input or step_input.previous_step_content or ""
    tech_keywords = ["ai", "machine learning", "programming", "software", "tech", "api", "database"]
    return any(keyword in str(topic).lower() for keyword in tech_keywords)


def is_long_content(step_input: StepInput) -> bool:
    """Check if previous step produced substantial content (>500 chars)."""
    content = step_input.previous_step_content or ""
    return len(str(content)) > 500


def requires_human_review(step_input: StepInput) -> bool:
    """Check if content contains sensitive topics requiring human review."""
    content = str(step_input.previous_step_content or step_input.input or "").lower()
    sensitive_keywords = ["legal", "medical", "financial advice", "lawsuit", "diagnosis"]
    return any(keyword in content for keyword in sensitive_keywords)


def has_errors_in_output(step_input: StepInput) -> bool:
    """Check if any previous step failed - useful for error handling branches."""
    outputs = step_input.previous_step_outputs or {}
    return any(not output.success for output in outputs.values())


def is_question(step_input: StepInput) -> bool:
    """Check if input is a question (ends with ? or starts with question words)."""
    text = str(step_input.input or "").strip().lower()
    question_starters = ["what", "why", "how", "when", "where", "who", "which", "can", "could", "would", "is", "are"]
    return text.endswith("?") or any(text.startswith(word) for word in question_starters)


# =============================================================================
# LOOP END CONDITIONS
# Functions that return True to break the loop, False to continue
# =============================================================================


def check_research_complete(outputs: List[StepOutput]) -> bool:
    """Break loop when research produces substantial content (>500 chars)."""
    if not outputs:
        return False
    latest = outputs[-1]
    return bool(latest.content and len(str(latest.content)) > 500)


def max_iterations_or_success(outputs: List[StepOutput]) -> bool:
    """Break loop after 3 iterations OR when a step reports success with 'DONE' marker."""
    if len(outputs) >= 3:
        return True
    if outputs:
        latest_content = str(outputs[-1].content or "").upper()
        return "DONE" in latest_content or "COMPLETE" in latest_content
    return False


def convergence_check(outputs: List[StepOutput]) -> bool:
    """Break loop when outputs stabilize (last 2 outputs are similar)."""
    if len(outputs) < 2:
        return False
    last_two = outputs[-2:]
    content_a = str(last_two[0].content or "")[:200]
    content_b = str(last_two[1].content or "")[:200]
    # Simple similarity: if 80% of words match, consider converged
    words_a = set(content_a.lower().split())
    words_b = set(content_b.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b) / max(len(words_a), len(words_b))
    return overlap > 0.8


def all_steps_successful(outputs: List[StepOutput]) -> bool:
    """Break loop only when all outputs in current iteration are successful."""
    if not outputs:
        return False
    return all(output.success for output in outputs)


def found_answer(outputs: List[StepOutput]) -> bool:
    """Break loop when output contains answer markers."""
    if not outputs:
        return False
    latest_content = str(outputs[-1].content or "").lower()
    answer_markers = ["the answer is", "in conclusion", "therefore", "result:", "solution:"]
    return any(marker in latest_content for marker in answer_markers)


# =============================================================================
# ROUTER SELECTORS
# Functions that return step name(s) to execute from available choices
# =============================================================================


def select_research_step(step_input: StepInput) -> List[str]:
    """Route to appropriate research step based on topic type."""
    topic = str(step_input.input or step_input.previous_step_content or "").lower()

    if any(kw in topic for kw in ["ai", "ml", "programming", "software", "tech"]):
        return ["TechResearchStep"]
    elif any(kw in topic for kw in ["news", "current events", "today"]):
        return ["NewsStep"]
    elif any(kw in topic for kw in ["science", "research", "study"]):
        return ["AcademicStep"]
    return ["GeneralSearchStep"]


def select_by_complexity(step_input: StepInput) -> List[str]:
    """Route based on input complexity - simple queries vs complex analysis."""
    text = str(step_input.input or "")
    word_count = len(text.split())

    if word_count < 10:
        return ["QuickAnswerStep"]
    elif word_count < 50:
        return ["StandardAnalysisStep"]
    else:
        return ["DeepAnalysisStep", "SummaryStep"]  # Multiple steps for complex input


def select_by_intent(step_input: StepInput) -> List[str]:
    """Route based on detected user intent."""
    text = str(step_input.input or "").lower()

    if any(word in text for word in ["create", "generate", "write", "make"]):
        return ["CreativeStep"]
    elif any(word in text for word in ["analyze", "compare", "evaluate"]):
        return ["AnalysisStep"]
    elif any(word in text for word in ["explain", "what is", "how does"]):
        return ["ExplanationStep"]
    elif any(word in text for word in ["fix", "debug", "error", "problem"]):
        return ["TroubleshootStep"]
    return ["GeneralStep"]


def select_parallel_tasks(step_input: StepInput) -> List[str]:
    """Select multiple steps to run in parallel based on input requirements."""
    text = str(step_input.input or "").lower()
    steps = []

    if "data" in text or "numbers" in text:
        steps.append("DataAnalysisStep")
    if "visual" in text or "chart" in text or "graph" in text:
        steps.append("VisualizationStep")
    if "report" in text or "summary" in text:
        steps.append("ReportStep")

    return steps if steps else ["DefaultStep"]


def select_by_language(step_input: StepInput) -> List[str]:
    """Route to language-specific processing steps."""
    text = str(step_input.input or "")

    # Simple language detection heuristics
    if any(ord(c) > 127 for c in text):
        if any("\u4e00" <= c <= "\u9fff" for c in text):
            return ["ChineseProcessingStep"]
        elif any("\u3040" <= c <= "\u309f" or "\u30a0" <= c <= "\u30ff" for c in text):
            return ["JapaneseProcessingStep"]
        return ["MultilingualStep"]
    return ["EnglishProcessingStep"]


registry = Registry(
    name="Agno Registry",
    tools=[DuckDuckGoTools(), sample_tool, CalculatorTools()],
    models=[
        OpenAIChat(id="gpt-5-mini"),
        OpenAIChat(id="gpt-5"),
        Claude(id="claude-sonnet-4-5"),
    ],
    dbs=[db],
    functions=[
        # Step executors
        transform_content,
        summarize_step_outputs,
        validate_input,
        # Condition evaluators
        is_tech_topic,
        is_long_content,
        requires_human_review,
        has_errors_in_output,
        is_question,
        # Loop end conditions
        check_research_complete,
        max_iterations_or_success,
        convergence_check,
        all_steps_successful,
        found_answer,
        # Router selectors
        select_research_step,
        select_by_complexity,
        select_by_intent,
        select_parallel_tasks,
        select_by_language,
    ],
)

agent = Agent(
    id="registry-agent",
    model=Claude(id="claude-sonnet-4-5"),
    db=db,
)

agent_os = AgentOS(
    agents=[agent],
    id="registry-agent-os",
    registry=registry,
    db=db,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agent_os_registry:app", reload=True)
