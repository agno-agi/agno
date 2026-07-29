"""
Tool Call Trajectories - Multi-Turn Simulation
==============================================

Multi-turn tool-use trajectories from a simulated user talking to a real
tool-wielding assistant. Two persona user-sim agents each pursue a small
multi-step calculation goal over up to 3 turns; the assistant actually
executes CalculatorTools calls, and the executed calls (name, arguments,
result) are extracted from each RunOutput. One JSONL row per conversation
with messages, executed tool calls, and turn count.
"""

import json
from pathlib import Path
from typing import Dict

from agno.agent import Agent, RunOutput
from agno.tools.calculator import CalculatorTools
from rich.pretty import pprint

MAX_TURNS = 3


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------
PERSONAS: Dict[str, str] = {
    "dinner_host": (
        "You are simulating a user planning a dinner for friends. Your goal, "
        "step by step: (1) find the cost of 4 pizzas at 18.50 each, (2) add "
        "the 12.75 delivery fee, (3) split the total evenly among 5 people."
    ),
    "math_student": (
        "You are simulating a student double-checking homework. Your goal, "
        "step by step: (1) find out whether 97 is a prime number, (2) compute "
        "12 factorial divided by 10 factorial."
    ),
}

SIM_RULES = (
    " Ask the assistant for one step at a time and never do the math "
    "yourself. React naturally to the assistant's answers in one or two "
    "sentences. When every step of your goal has been answered, end your "
    "message with the single word DONE."
)


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
USER_SIMS: Dict[str, Agent] = {
    persona: Agent(model="google:gemini-3.5-flash", instructions=goal + SIM_RULES)
    for persona, goal in PERSONAS.items()
}

assistant = Agent(
    model="google:gemini-3.5-flash",
    tools=[CalculatorTools()],
    instructions=(
        "You are a precise assistant with calculator tools. Use the tools "
        "for every arithmetic step instead of computing in your head. Keep "
        "replies to one or two short sentences with the numeric result."
    ),
)


# ---------------------------------------------------------------------------
# Simulation Loop
# ---------------------------------------------------------------------------
def render_transcript(messages: list) -> str:
    return "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)


def run_conversation(persona: str) -> dict:
    """Run one simulated conversation and return its trajectory row."""
    user_sim = USER_SIMS[persona]
    messages: list = []
    tool_calls: list = []
    turns = 0
    for _ in range(MAX_TURNS):
        if messages:
            sim_prompt = (
                "Conversation so far:\n"
                + render_transcript(messages)
                + "\n\nWrite your next user message."
            )
        else:
            sim_prompt = "Start the conversation with your first request."
        sim_run: RunOutput = user_sim.run(sim_prompt)
        user_text = str(sim_run.content).strip()
        done = user_text.endswith("DONE")
        if done:
            user_text = user_text[: user_text.rfind("DONE")].strip()
        if not user_text:
            break  # the sim had nothing left to say but DONE
        messages.append({"role": "user", "content": user_text})

        assistant_run: RunOutput = assistant.run(
            "Conversation so far:\n"
            + render_transcript(messages)
            + "\n\nReply to the last user message."
        )
        messages.append(
            {"role": "assistant", "content": str(assistant_run.content).strip()}
        )
        for tool in assistant_run.tools or []:
            tool_calls.append(
                {
                    "tool_name": tool.tool_name,
                    "arguments": tool.tool_args,
                    "result": tool.result,
                }
            )
        turns += 1
        if done:
            break
    return {
        "persona": persona,
        "messages": messages,
        "tool_calls": tool_calls,
        "turns": turns,
    }


# ---------------------------------------------------------------------------
# Run Simulation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "multi_turn_trajectories.jsonl"

    rows = []
    for persona in PERSONAS:
        row = run_conversation(persona)
        print(
            f"{persona}: {row['turns']} turns, {len(row['tool_calls'])} executed tool calls"
        )
        rows.append(row)

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    pprint(rows[0]["tool_calls"])
    total_turns = sum(row["turns"] for row in rows)
    total_calls = sum(len(row["tool_calls"]) for row in rows)
    print(
        f"wrote {len(rows)} rows to {out_path}, total {total_turns} turns, {total_calls} executed tool calls"
    )
