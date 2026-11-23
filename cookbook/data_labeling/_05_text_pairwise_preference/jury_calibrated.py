"""A calibration-first jury: jurors earn their vote weight on gold pairs.

Before judging anything real, every juror is scored on a balanced gold set
(5 gold=a / 5 gold=b, both orderings) and gets an attributed report card:
gold accuracy, Brier score on verbalized confidence, and a position-bias
check. Jurors below the accuracy floor are dropped from the jury; the
survivors vote with accuracy-derived weights, and every DPO record carries
the per-juror votes, confidences, and weights.
"""

import asyncio
import json
from typing import Literal

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field


class Verdict(BaseModel):
    winner: Literal["a", "b", "tie"]
    confidence: float = Field(
        ge=0, le=1, description="Probability that this verdict is correct"
    )


RUBRIC = """\
Pick the more correct, more helpful answer; ties are allowed. Never reward
length or a confident tone. Set confidence to your probability that your
verdict is correct: 0.5 means a coin flip, 0.95 means nearly certain.
"""


def juror(model) -> Agent:
    return Agent(model=model, instructions=RUBRIC, output_schema=Verdict)


JURY: dict[str, Agent] = {
    # gpt-5.5 and claude-sonnet-5 reject the temperature parameter
    "openai": juror(OpenAIResponses(id="gpt-5.5")),
    "anthropic": juror(Claude(id="claude-sonnet-5")),
    "google": juror(Gemini(id="gemini-3.5-flash", temperature=0)),
}

ACCURACY_FLOOR = 0.6  # jurors below this gold accuracy do not vote

# Balanced gold set: 5 gold=a and 5 gold=b, difficulty-matched across the
# halves (two clear, two near-tie, one arithmetic each). With a balanced
# set, an unbiased juror's first-slot rate sits near 0.5 and a position
# bias cannot pass as accuracy.
GOLD: list[dict] = [
    dict(
        id="sort",
        gold="a",
        prompt="What does Python's list.sort() return?",
        a="None - it sorts in place; use sorted(lst) if you need the sorted list as a value.",
        b="The sorted list, so you can chain calls like lst.sort().reverse().",
    ),
    dict(
        id="where",
        gold="a",
        prompt="In SQL, does WHERE filter before or after GROUP BY aggregation?",
        a="Before - WHERE filters rows prior to grouping; HAVING filters after aggregation.",
        b="After - WHERE applies to grouped results, which is why you can reference aggregates in it.",
    ),
    dict(
        id="lfront",
        gold="a",
        prompt="What is the time complexity of inserting at index 0 of a Python list?",
        a="O(n) - every existing element shifts right by one slot.",
        b="Amortized O(1) - Python lists over-allocate, so front inserts reuse the spare capacity.",
    ),
    dict(
        id="h2hol",
        gold="a",
        prompt="Does HTTP/2 eliminate head-of-line blocking entirely?",
        a="No - it removes HTTP-level blocking via stream multiplexing, but TCP-level head-of-line blocking remains; QUIC addresses that layer.",
        b="Yes - streams are independent, so one stalled response no longer delays the others on the connection.",
    ),
    dict(
        id="gauss",
        gold="a",
        prompt="What is the sum of the first 100 positive integers?",
        a="5050, by pairing: 100*101/2.",
        b="5000: fifty pairs each summing to 100 gives 50*100.",
    ),
    dict(
        id="boolstr",
        gold="b",
        prompt="In Python, what is bool('False')?",
        a="False - the string parses as the boolean literal False.",
        b="True - any non-empty string is truthy, regardless of its content.",
    ),
    dict(
        id="stashpop",
        gold="b",
        prompt="What does git stash pop do if applying the stash conflicts?",
        a="It applies what it can and drops the stash entry; re-run git stash to recreate it.",
        b="It applies the changes, reports conflicts, and keeps the stash entry; you drop it manually after resolving.",
    ),
    dict(
        id="udp",
        gold="b",
        prompt="Do UDP datagrams preserve message boundaries?",
        a="No - like TCP, UDP delivers a byte stream and applications must add their own framing.",
        b="Yes - each sendto() maps to one recvfrom(); boundaries are preserved, though datagrams may drop or reorder.",
    ),
    dict(
        id="dictord",
        gold="b",
        prompt="Is iteration order of a Python dict guaranteed?",
        a="No - dicts are hash tables; iteration order is arbitrary and may change between runs, so use OrderedDict when order matters.",
        b="Yes - since Python 3.7, dicts preserve insertion order as a language guarantee.",
    ),
    dict(
        id="coin",
        gold="b",
        prompt="A fair coin is flipped 3 times. What is the probability of at least one head?",
        a="3/4: P(at least one head) = 1 - P(no heads) = 1 - 1/4.",
        b="7/8: the only all-tails outcome has probability (1/2)^3 = 1/8, so 1 - 1/8 = 7/8.",
    ),
]

# Raw DPO candidates: the same three pairs dpo_jury.py labels.
RAW: list[dict] = [
    dict(
        id="fib",
        prompt="Write an iterative Python fib(n), with fib(0) = 0.",
        a="def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a",
        b="def fib(n):\n    a, b = 0, 1\n    for _ in range(n - 1):\n        a, b = b, a + b\n    return b",
    ),
    dict(
        id="is_even",
        prompt="Write is_even(n) for Python integers.",
        a="def is_even(n):\n    return n % 2 == 0",
        b="def is_even(n):\n    return not n & 1",
    ),
    dict(
        id="reset",
        prompt="What does git reset --soft HEAD~1 do?",
        a="Moves the branch back one commit; the undone commit's changes remain staged; working tree untouched.",
        b="Moves the branch back one commit and unstages those changes, leaving them as edits in your working tree.",
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


async def judge(family: str, ex: dict) -> dict:
    fwd = await ask(JURY[family], ex["prompt"], ex["a"], ex["b"])
    rev = await ask(JURY[family], ex["prompt"], ex["b"], ex["a"])  # same pair, swapped
    return {
        # order-sensitive verdicts become ties
        "winner": fwd.winner if fwd.winner == SWAP[rev.winner] else "tie",
        "confidence": (fwd.confidence + rev.confidence) / 2,
        "flipped": fwd.winner != SWAP[rev.winner],
        # in both orderings the label "a" is the first-presented answer
        "first_slot_picks": [fwd.winner, rev.winner].count("a"),
        "decisive": sum(1 for v in (fwd, rev) if v.winner != "tie"),
    }


async def calibrate(family: str) -> dict:
    results = await asyncio.gather(*[judge(family, ex) for ex in GOLD])
    correct = [r["winner"] == ex["gold"] for r, ex in zip(results, GOLD)]
    # Brier on verbalized confidence: mean of (confidence - outcome)^2 where
    # outcome is 1 if the debiased verdict matched gold. 0 is perfect
    # calibration; 0.25 is what a coin-flip juror saying 0.5 scores. An
    # order-flipped verdict counts as wrong while keeping its stated
    # confidence, so flip-prone overconfidence is penalized.
    brier = sum(
        (r["confidence"] - (1.0 if c else 0.0)) ** 2 for r, c in zip(results, correct)
    ) / len(GOLD)
    decisive = sum(r["decisive"] for r in results)
    return {
        "family": family,
        "accuracy": sum(correct) / len(GOLD),
        "brier": brier,
        "order_flips": sum(r["flipped"] for r in results),
        "first_slot_rate": (
            sum(r["first_slot_picks"] for r in results) / decisive if decisive else 0.0
        ),
    }


async def main() -> None:
    cards = await asyncio.gather(*[calibrate(family) for family in JURY])
    print("-- juror report cards: 10 balanced gold pairs, both orderings --")
    for card in cards:
        print(
            f"{card['family']:<10} gold accuracy {card['accuracy']:.2f}  "
            f"brier {card['brier']:.3f}  order flips {card['order_flips']}/10  "
            f"first-slot rate {card['first_slot_rate']:.2f}"
        )

    for card in cards:
        if card["accuracy"] < ACCURACY_FLOOR:
            print(
                f"dropped: {card['family']} gold accuracy {card['accuracy']:.2f} "
                f"is below the {ACCURACY_FLOOR} floor"
            )
    survivors = [c for c in cards if c["accuracy"] >= ACCURACY_FLOOR]
    total = sum(c["accuracy"] for c in survivors)
    weights = {c["family"]: c["accuracy"] / total for c in survivors}
    print("weights: " + ", ".join(f"{f} {w:.2f}" for f, w in weights.items()))

    results = await asyncio.gather(
        *[asyncio.gather(*[judge(family, ex) for family in weights]) for ex in RAW]
    )
    dpo, review = [], []
    for ex, votes in zip(RAW, results):
        tally = {"a": 0.0, "b": 0.0, "tie": 0.0}
        for family, vote in zip(weights, votes):
            tally[vote["winner"]] += weights[family]
        winner, share = max(tally.items(), key=lambda kv: kv[1])
        if sum(1 for v in tally.values() if v == share) > 1:
            winner = "tie"  # split vote
        attributed = {
            family: {
                "winner": vote["winner"],
                "confidence": round(vote["confidence"], 2),
                "weight": round(weights[family], 2),
            }
            for family, vote in zip(weights, votes)
        }
        if winner != "tie" and share >= 0.75:
            dpo.append(
                {
                    "prompt": ex["prompt"],
                    "chosen": ex[winner],
                    "rejected": ex[SWAP[winner]],
                    "weighted_agreement": round(share, 2),
                    "votes": attributed,
                }
            )
        else:
            review.append(
                f"{ex['id']}: winner={winner}, weighted_agreement={share:.2f}, "
                f"votes={json.dumps(attributed)}"
            )

    print("\n-- dpo records: accuracy-weighted vote, per-juror attribution --")
    for record in dpo:
        print(json.dumps(record))
    print("\n-- needs a human --")
    for item in review:
        print(item)
    print(f"\n{len(dpo)} dpo records, {len(review)} routed to review")


asyncio.run(main())
