"""A jury of 5 models turns raw response pairs into trainer-ready DPO data."""

import asyncio
import json
from collections import Counter
from typing import Literal

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.mistral import MistralChat
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field


class Verdict(BaseModel):
    winner: Literal["a", "b", "tie"]
    confidence: float = Field(ge=0, le=1)


RUBRIC = "Pick the more correct, more helpful answer; ties are allowed. Never reward length or a confident tone."


def juror(model) -> Agent:
    return Agent(model=model, instructions=RUBRIC, output_schema=Verdict)


JURY: dict[str, Agent] = {  # one juror per model family
    "openai": juror(OpenAIResponses(id="gpt-5.5")),
    "anthropic": juror(Claude(id="claude-sonnet-5")),
    "google": juror(Gemini(id="gemini-3.5-flash", temperature=0)),
    "qwen": juror(Groq(id="qwen/qwen3.6-27b", temperature=0)),
    "mistral": juror(MistralChat(id="mistral-large-latest", temperature=0)),
}
# gold pairs calibrate the jury; the rest are raw DPO candidates
EXAMPLES: list[dict] = [
    dict(
        id="fib",
        source_family="xai",
        gold=None,
        prompt="Write an iterative Python fib(n), with fib(0) = 0.",
        a="def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a",
        b="def fib(n):\n    a, b = 0, 1\n    for _ in range(n - 1):\n        a, b = b, a + b\n    return b",
    ),
    dict(
        id="is_even",
        source_family="deepseek",
        gold=None,
        prompt="Write is_even(n) for Python integers.",
        a="def is_even(n):\n    return n % 2 == 0",
        b="def is_even(n):\n    return not n & 1",
    ),
    dict(
        id="reset",
        source_family="anthropic",
        gold=None,
        prompt="What does git reset --soft HEAD~1 do?",
        a="Moves the branch back one commit; the undone commit's changes remain staged; working tree untouched.",
        b="Moves the branch back one commit and unstages those changes, leaving them as edits in your working tree.",
    ),
    dict(
        id="g-incl",
        source_family="meta",
        gold="a",
        prompt="How many integers from 1 to 1000 are divisible by 3 or 5?",
        a="467: floor(1000/3)=333, floor(1000/5)=200, subtract floor(1000/15)=66 counted twice: 333+200-66=467.",
        b="533: there are 333 multiples of 3 and 200 multiples of 5, giving 533 integers divisible by 3 or 5.",
    ),
    dict(
        id="g-round",
        source_family="xai",
        gold="a",
        prompt="In Python 3, what is round(2.5) and why?",
        a="2. Python 3 uses banker's rounding: halves go to the nearest even integer, so 2.5 rounds down to 2.",
        b="3. Python rounds .5 up, as in standard arithmetic, so round(2.5) is 3.",
    ),
    dict(
        id="g-tcp",
        source_family="deepseek",
        gold="a",
        prompt="Does TCP preserve message boundaries across send()/recv()?",
        a="No. TCP is a byte stream: one send may arrive across several recvs, so applications must frame messages.",
        b="Yes. Each send() maps to one recv() on the peer, so boundaries survive while the connection stays open.",
    ),
]
SWAP = {"a": "b", "b": "a", "tie": "tie"}
SEM = asyncio.Semaphore(8)  # stay under provider rate limits


async def ask(agent: Agent, prompt: str, first: str, second: str) -> Verdict:
    for attempt in range(4):  # retry schema breaks and rate limits, never coerce
        async with SEM:
            run = await agent.arun(
                f"PROMPT:\n{prompt}\n\nANSWER a:\n{first}\n\nANSWER b:\n{second}"
            )
        if isinstance(run.content, Verdict):
            return run.content
        await asyncio.sleep(2**attempt)
    raise RuntimeError(f"juror {agent.model.id} would not produce a valid Verdict")


async def judge(family: str, ex: dict) -> dict | None:
    if family == ex["source_family"]:
        print(f"recusal: {family} sits out '{ex['id']}' - it wrote these responses")
        return None
    fwd = await ask(JURY[family], ex["prompt"], ex["a"], ex["b"])
    rev = await ask(JURY[family], ex["prompt"], ex["b"], ex["a"])  # same pair, swapped
    winner = (
        fwd.winner if fwd.winner == SWAP[rev.winner] else "tie"
    )  # order-sensitive verdicts become ties
    return {
        "family": family,
        "winner": winner,
        "confidence": (fwd.confidence + rev.confidence) / 2,
    }


async def main() -> None:
    results = await asyncio.gather(
        *[asyncio.gather(*[judge(f, ex) for f in JURY]) for ex in EXAMPLES]
    )
    gold_right, gold_total, dpo, review = 0, 0, [], []
    for ex, jury_votes in zip(EXAMPLES, results):
        votes = [v for v in jury_votes if v is not None]
        winner, count = Counter(v["winner"] for v in votes).most_common(1)[0]
        agreement = count / len(votes)
        confidence = sum(v["confidence"] for v in votes) / len(votes)
        if ex["gold"]:
            gold_right, gold_total = gold_right + (winner == ex["gold"]), gold_total + 1
        elif winner != "tie" and agreement >= 0.75:
            dpo.append(
                {
                    "prompt": ex["prompt"],
                    "chosen": ex[winner],
                    "rejected": ex[SWAP[winner]],
                    "agreement": agreement,
                    "confidence": round(confidence, 2),
                    "votes": {v["family"]: v["winner"] for v in votes},
                }
            )
        else:
            review.append(
                f"{ex['id']}: winner={winner}, agreement={agreement:.2f}, confidence={confidence:.2f}"
            )
    print("\n-- dpo records --")
    for record in dpo:
        print(json.dumps(record))
    print("\n-- needs a human --")
    for item in review:
        print(item)
    print(f"\njury calibration: {gold_right}/{gold_total} gold pairs labeled correctly")


asyncio.run(main())
