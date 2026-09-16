# Feedback Labeler

Label feedback while retaining the original input and review decisions.
A small runnable companion to [Feedback Labeler](https://docs.agno.com/use-cases/data-labeling/overview).

## Run locally

From the repository root (or start inside the downloaded example directory):

```bash
cd cookbook/examples/feedback_labeler
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python demo.py
```

The demo writes three records to `labels.jsonl`: a bug, a feature request, and
mixed feedback that needs review. Each record retains a stable input ID, original
text, model, policy version, and proposed label. Failed runs also produce a record
with an error and `needs_review=true`. Running the demo again replaces this small
output file. `python label_feedback.py` runs the single-record docs example.

Structured validation checks shape, not classification accuracy. Inspect the
labels against a human reference set before accepting them into a dataset. The
[quality pipeline guide](https://docs.agno.com/use-cases/data-labeling/quality-pipeline)
adds multiple labelers, agreement checks, and adjudication.

## Build further

Read the linked use-case guide for the next step. Choose a
[deployment template](https://docs.agno.com/deploy/introduction) when you need a
fully deployable application. All examples here use OpenAI's `gpt-5.6`; model
responses vary. See [TEST_LOG.md](TEST_LOG.md) for what has been validated.
