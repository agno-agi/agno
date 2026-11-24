# Test Log - _03_text_extraction

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Extracts a flat `Contact` (name, email, phone, company, title) from two email-signature-style samples using `output_schema`.

**Result:** Sample 1 extracted all fields verbatim: name='Sarah Johnson', email='sarah@acme.com', phone='+1-555-0102', company='Acme Corp.', title='VP of Marketing'. Sample 2 extracted name='Mike', email='engineering@startup.io' with phone, company, and title left None as instructed.

---

### nested.py

**Status:** PASS

**Description:** Extracts a `Meeting` containing a list of nested `ActionItem` objects (owner, description, due_date) from a four-line meeting transcript; vague group asks are to be ignored.

**Result:** Three action items extracted with correct owners: Mike ('Send out the updated roadmap'), Sarah ('Set up the kickoff with the design team'), Mike ('Draft the budget memo'). Jess's vague 'budget approval at some point' was correctly excluded. All due_date fields were None this run - the transcript only contains relative dates ('by Friday', 'end of next week'), which the model did not resolve to ISO dates.

---

### with_confidence.py

**Status:** PASS

**Description:** Same contact-extraction task with each field wrapped in a `ConfidentField` (value plus Literal high/medium/low confidence) to support routing low-confidence fields to review.

**Result:** Sample 1 (full signature) returned all five fields with confidence='high' and verbatim values. Sample 2 ('ping @mike on the eng team') returned name=('mike', high), title=('eng team', medium), and email/phone/company as (None, low). Confidence spread is sensible, though name='mike' at 'high' and 'eng team' as a title are looser calls this run.

---
