"""
Persona-Driven Generation - Diversity Report
============================================

Does persona conditioning actually widen coverage, or does it just feel like
it? This file measures it. It generates N=8 prompts about the same fixed
domain twice - once unconditioned (one agent, one call, 8 prompts) and once
conditioned on 8 hand-written personas (one call per persona, 1 prompt
each) - then computes lexical diversity in pure stdlib: distinct-1 and
distinct-2 (unique n-grams / total n-grams over the pooled prompts) and
mean pairwise Jaccard distance between prompt word sets. The printed report
is the artifact; the verdict cites the numbers whichever way they point.
"""

from itertools import combinations

from agno.agent import Agent, RunOutput
from pydantic import BaseModel, Field

DOMAIN = "personal finance"
N = 8

# ---------------------------------------------------------------------------
# Personas (hand-written, one per conditioned prompt)
# ---------------------------------------------------------------------------
PERSONAS = [
    {
        "occupation": "third-generation dairy farmer",
        "expertise_level": "novice",
        "communication_style": "plainspoken and practical",
        "current_concern": "volatile milk prices eating into savings",
    },
    {
        "occupation": "emergency room nurse",
        "expertise_level": "novice",
        "communication_style": "hurried and direct",
        "current_concern": "what to do with night-shift differential pay",
    },
    {
        "occupation": "retired navy submariner",
        "expertise_level": "intermediate",
        "communication_style": "formal and precise",
        "current_concern": "sequencing pension drawdown with part-time work",
    },
    {
        "occupation": "freelance illustrator",
        "expertise_level": "novice",
        "communication_style": "casual and a little anxious",
        "current_concern": "smoothing wildly irregular monthly income",
    },
    {
        "occupation": "quantitative hedge fund analyst",
        "expertise_level": "expert",
        "communication_style": "terse and technical",
        "current_concern": "tax-efficient handling of deferred equity compensation",
    },
    {
        "occupation": "recently immigrated restaurant cook",
        "expertise_level": "novice",
        "communication_style": "simple English, cautious",
        "current_concern": "sending remittances home while building local credit",
    },
    {
        "occupation": "high school economics teacher",
        "expertise_level": "intermediate",
        "communication_style": "didactic and example-driven",
        "current_concern": "college funds for twin daughters",
    },
    {
        "occupation": "crypto day trader",
        "expertise_level": "intermediate",
        "communication_style": "slangy and extremely online",
        "current_concern": "harvesting losses from a bad quarter",
    },
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Prompts(BaseModel):
    prompts: list[str] = Field(
        ..., description="Self-contained questions a person might ask about the domain"
    )


class OnePrompt(BaseModel):
    prompt: str = Field(
        ...,
        description="A single self-contained question this persona would ask about the domain, in their voice",
    )


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
unconditioned_agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You write questions people ask about a domain. Each question must be "
        "self-contained and the questions should differ from each other."
    ),
    output_schema=Prompts,
)

conditioned_agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You write questions on behalf of a persona. The question must be one "
        "THIS person would actually ask about the domain: grounded in their "
        "occupation and current concern, phrased in their communication "
        "style, pitched at their expertise level, and self-contained. "
        "Keep the language family-friendly regardless of persona."
    ),
    output_schema=OnePrompt,
)


# ---------------------------------------------------------------------------
# Diversity Metrics (stdlib)
# ---------------------------------------------------------------------------
def tokenize(text: str) -> list:
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower())
    return cleaned.split()


def distinct_n(prompt_list: list, n: int) -> float:
    pooled = []
    for text in prompt_list:
        tokens = tokenize(text)
        pooled.extend(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))
    if not pooled:
        return 0.0
    return len(set(pooled)) / len(pooled)


def mean_pairwise_jaccard_distance(prompt_list: list) -> float:
    word_sets = [set(tokenize(text)) for text in prompt_list]
    distances = [
        1.0 - len(a & b) / len(a | b) for a, b in combinations(word_sets, 2) if a | b
    ]
    if not distances:
        return 0.0
    return sum(distances) / len(distances)


def build_request(persona: dict) -> str:
    lines = [
        "Persona:",
        f"- occupation: {persona['occupation']}",
        f"- expertise_level: {persona['expertise_level']}",
        f"- communication_style: {persona['communication_style']}",
        f"- current_concern: {persona['current_concern']}",
        "",
        f"Write the one question about {DOMAIN} this persona would most plausibly ask.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run Comparison
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run: RunOutput = unconditioned_agent.run(
        f"Write {N} questions a person might ask about {DOMAIN}."
    )
    unconditioned = [p.strip() for p in run.content.prompts[:N]]

    conditioned = []
    for persona in PERSONAS:
        persona_run: RunOutput = conditioned_agent.run(build_request(persona))
        conditioned.append(persona_run.content.prompt.strip())

    print("-- unconditioned prompts --")
    for prompt in unconditioned:
        print(f"  {prompt}")
    print("\n-- persona-conditioned prompts --")
    for prompt in conditioned:
        print(f"  {prompt}")

    metrics = [
        ("distinct-1", distinct_n(unconditioned, 1), distinct_n(conditioned, 1)),
        ("distinct-2", distinct_n(unconditioned, 2), distinct_n(conditioned, 2)),
        (
            "mean pairwise jaccard distance",
            mean_pairwise_jaccard_distance(unconditioned),
            mean_pairwise_jaccard_distance(conditioned),
        ),
    ]

    print("\n-- diversity report --")
    header = f"{'metric':<32} {'unconditioned':>14} {'conditioned':>12}"
    print(header)
    for name, u_val, c_val in metrics:
        print(f"{name:<32} {u_val:>14.3f} {c_val:>12.3f}")
    u_len = sum(len(tokenize(p)) for p in unconditioned) / len(unconditioned)
    c_len = sum(len(tokenize(p)) for p in conditioned) / len(conditioned)
    print(f"{'mean tokens per prompt (context)':<32} {u_len:>14.1f} {c_len:>12.1f}")
    print(
        "note: distinct-n is length-sensitive - longer prompts repeat more "
        "function words, which depresses distinct-1 independent of topical spread"
    )

    gains = [name for name, u_val, c_val in metrics if c_val > u_val]
    detail = ", ".join(
        f"{name} {u_val:.3f} -> {c_val:.3f}" for name, u_val, c_val in metrics
    )
    if len(gains) == len(metrics):
        print(f"\nverdict: persona conditioning increased all three metrics ({detail})")
    elif not gains:
        print(
            f"\nverdict: persona conditioning did not increase any metric this run ({detail})"
        )
    else:
        losses = [name for name, _, _ in metrics if name not in gains]
        print(
            f"\nverdict: mixed - conditioning increased {', '.join(gains)} "
            f"but not {', '.join(losses)} ({detail})"
        )
    print(
        f"compared {len(unconditioned)} unconditioned vs {len(conditioned)} conditioned prompts"
    )
