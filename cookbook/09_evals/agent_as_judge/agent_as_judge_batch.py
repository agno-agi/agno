"""Batch evaluation example - evaluate multiple cases at once."""

from agno.db.sqlite import SqliteDb
from agno.eval.agent_as_judge import AgentAsJudgeEval

# Setup database to persist eval results
db = SqliteDb(db_file="tmp/agent_as_judge_batch.db")

evaluation = AgentAsJudgeEval(
    name="Customer Service Quality",
    criteria="Response should be empathetic, professional, and helpful",
    scoring_strategy="binary",  # PASS/FAIL for each case
    # For numeric scoring (1-10 with threshold), use:
    # scoring_strategy="numeric",
    # threshold=7,
    db=db,
)

result = evaluation.run(
    cases=[
        {
            "input": "My order is delayed and I'm very upset!",
            "output": "I sincerely apologize for the delay. I understand how frustrating this must be. Let me check your order status right away and see how we can make this right for you.",
        },
        {
            "input": "Can you help me with a refund?",
            "output": "Of course! I'd be happy to help with your refund. Could you please provide your order number so I can process this quickly for you?",
        },
        {
            "input": "Your product is terrible!",
            "output": "I'm sorry to hear you're disappointed. Your feedback is valuable to us. Could you share more details about what went wrong so we can improve?",
        },
    ],
    print_results=True,
    print_summary=True,
)

print(f"Pass rate: {result.pass_rate:.1f}%")
print(f"Passed: {sum(1 for r in result.results if r.passed)}/{len(result.results)}")

# Query database for stored results
print("Database Results:")
eval_runs = db.get_eval_runs()
print(f"Total evaluations stored: {len(eval_runs)}")
if eval_runs:
    latest = eval_runs[-1]
    print(f"Eval ID: {latest.run_id}")
    print(f"Cases evaluated: {len(result.results)}")
