"""
Instruction Generation - Topic Tree
===================================

Generate SFT-ready chat data by walking a topic tree: root topic ->
subtopics -> questions -> responses. Three agents split the pipeline
(expander, question writer, answerer), and every row carries provenance
back to the branch of the tree that produced it, so downstream filters can
prune whole subtopics at once.
"""

import json
from pathlib import Path

from agno.agent import Agent, RunOutput
from pydantic import BaseModel, Field
from rich.pretty import pprint

ROOT_TOPIC = "database indexing"
NUM_SUBTOPICS = 3
QUESTIONS_PER_SUBTOPIC = 2


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class Subtopics(BaseModel):
    subtopics: list[str] = Field(
        ..., description="Distinct, non-overlapping subtopics of the given topic"
    )


class Questions(BaseModel):
    questions: list[str] = Field(
        ...,
        description="Specific, self-contained questions a practitioner would ask about the subtopic",
    )


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
expander = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You expand a technical topic into distinct subtopics. Subtopics "
        "must not overlap and must each be substantial enough to generate "
        "several questions."
    ),
    output_schema=Subtopics,
)

question_writer = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You write specific, self-contained technical questions about a "
        "subtopic. Each question must be answerable without external "
        "context and must not duplicate the others."
    ),
    output_schema=Questions,
)

answerer = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You answer technical questions clearly and concretely in one or "
        "two short paragraphs. No preamble, no closing remarks."
    ),
)


# ---------------------------------------------------------------------------
# Run Pipeline
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "topic_tree.jsonl"

    expand_run: RunOutput = expander.run(
        f"Topic: {ROOT_TOPIC}\nList exactly {NUM_SUBTOPICS} distinct subtopics."
    )
    subtopics = expand_run.content.subtopics[:NUM_SUBTOPICS]

    rows = []
    for subtopic in subtopics:
        question_run: RunOutput = question_writer.run(
            f"Topic: {ROOT_TOPIC}\nSubtopic: {subtopic}\n"
            f"Write exactly {QUESTIONS_PER_SUBTOPIC} questions."
        )
        questions = question_run.content.questions[:QUESTIONS_PER_SUBTOPIC]

        for question in questions:
            answer_run: RunOutput = answerer.run(question)
            rows.append(
                {
                    "messages": [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": answer_run.content},
                    ],
                    "provenance": {
                        "topic": ROOT_TOPIC,
                        "subtopic": subtopic,
                        "depth": 3,
                    },
                }
            )

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    pprint(rows[:1])
    n = len(rows)
    print(
        f"wrote {n} rows to {out_path} ({len(subtopics)} subtopics x up to {QUESTIONS_PER_SUBTOPIC} questions each)"
    )
