"""Label a tiny dataset, retaining input, policy, and failed records for review."""

import json
from pathlib import Path

from agno.run.base import RunStatus
from label_feedback import MODEL_ID, POLICY_VERSION, FeedbackLabel, labeler

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    inputs = [
        ("feedback-1", "CSV export fails whenever I select more than one project."),
        ("feedback-2", "Please add weekly email reports."),
        ("feedback-3", "I love the dashboard, but CSV export is broken."),
    ]
    records = []
    for input_id, text in inputs:
        record = {
            "id": input_id,
            "input": text,
            "model": MODEL_ID,
            "policy_version": POLICY_VERSION,
            "label": None,
            "needs_review": True,
        }
        try:
            result = labeler.run(text)
            if result.status != RunStatus.completed or not isinstance(
                result.content, FeedbackLabel
            ):
                raise RuntimeError("No validated label")
            record["label"] = result.content.model_dump()
            record["needs_review"] = result.content.topic == "needs_review"
        except Exception as error:
            record["error"] = str(error)
        records.append(record)
    Path("labels.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )
    print(json.dumps(records, indent=2))
    print("Saved labels.jsonl; inspect proposed labels and records needing review.")
