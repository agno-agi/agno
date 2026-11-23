# Structured Extraction

Turn conflicting prose into a typed record after applying explicit source,
amendment, and cancellation rules.

## Files

- `basic.py` — extracts the operative account record from signed documents
  and non-operative drafts.
- `conflicting_fields.py` — resolves each shipment field using source-specific
  precedence and reconciles discarded evidence with an audit checksum.
- `nested_records.py` — reconciles amended items and shipments into a sorted
  nested object.

## When to use

Use typed extraction when correctness is the complete structured object, not a
plausible prose summary. Include precedence rules in the policy and score every
field; easy, conflict-free records often saturate and conceal the useful band.

This builds on bounded repairs in [`_23_code_fixes/`](../_23_code_fixes/).
Continue to [`_25_support_triage/`](../_25_support_triage/) for precedence-heavy
classification and escalation.

## Run

```bash
python cookbook/environments/_24_structured_extraction/basic.py
python cookbook/environments/_24_structured_extraction/conflicting_fields.py
python cookbook/environments/_24_structured_extraction/nested_records.py
```

Requires `OPENAI_API_KEY`. Every model call uses `OpenAIResponses` with
`gpt-5.5`.
