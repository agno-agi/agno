# Test Log - _04_text_span_labeling

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** NER over a short sentence using an output_schema of (text, label) pairs with labels PERSON, ORG, LOCATION, DATE; character offsets are computed in Python via `text.find()` rather than by the model.

**Result:** Five entities returned with correct offsets: DATE 'March 3rd' (3-12), PERSON 'Sarah Johnson' (14-27), ORG 'Acme Corp' (33-42), LOCATION 'Berlin' (70-76), ORG 'Lumen Labs' (84-94). Run took about 2.9s.

---

### pii_redaction.py

**Status:** PASS

**Description:** PII span detection (email, phone, ssn, credit_card, person_name) followed by a Python find-and-replace redaction step that substitutes each span with a [TYPE] token.

**Result:** All four PII items detected: person_name 'Jane Doe', phone '415-555-0199', email 'jane.doe@example.com', credit_card '4242 4242 4242 4242'. Redacted output: "Customer [PERSON_NAME] called from [PHONE] about her order. She asked us to email [EMAIL] with the receipt. Card on file ends [CREDIT_CARD]." Run took about 2.9s.

---
