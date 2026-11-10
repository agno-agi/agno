# Data labeling

Agents for labeling, classification, and synthetic data generation. 28 folders: 75 single-file runnable examples plus the `image_search` app (81 Python files in all).

Each subfolder holds examples for one theme, containing a `basic.py` that runs end-to-end, plus variants that add task-meaningful options on top.

Workflows are organized by modality (text, image, audio, video, document) and output shape (classify, extract, rank, span-label). Further patterns (`_17_llm_as_judge`, `_18_quality_review`, `_19_inter_annotator_agreement`) compose on top of any of these, and the synthetic-data workflows (`_20`-`_25`) generate and curate training data rather than label existing inputs.

Start with [`_01_text_classification/basic.py`](_01_text_classification/basic.py). Every other cookbook mirrors its structure.

## Layout

````
cookbook/data_labeling/
├── README.md
├── <workflow>/
│   ├── README.md
│   ├── basic.py            # smallest readable example
│   ├── <variant>.py        # one file per task-meaningful variant
│   ├── schemas.py          # shared Pydantic types, if any
│   ├── data/               # sample inputs or dataset pointers
│   └── TEST_LOG.md         # run log per the cookbook convention
└── ...
````

## Workflows

### Text
- [`_01_text_classification/`](_01_text_classification/): assign one of N labels (sentiment, intent, topic).
- [`_02_text_multilabel_classification/`](_02_text_multilabel_classification/): assign any subset of N tags, optionally hierarchical.
- [`_03_text_extraction/`](_03_text_extraction/): text into a typed Pydantic object (entities, fields, nested structures).
- [`_04_text_span_labeling/`](_04_text_span_labeling/): mark character or token spans (NER, PII detection, claim and evidence highlighting).
- [`_05_text_pairwise_preference/`](_05_text_pairwise_preference/): rank A vs B against a rubric (RLHF data shape).

### Image
- [`_06_image_classification/`](_06_image_classification/): single or multi-label per image.
- [`_07_image_extraction/`](_07_image_extraction/): image into a typed object (attributes, OCR fields, captions).
- [`_09_image_extraction_to_vectordb/`](_09_image_extraction_to_vectordb/): extract, embed, and store for similarity search.
- [`_08_image_bounding_boxes/`](_08_image_bounding_boxes/): region detection with `(x, y, w, h)` per object.

### Audio
- [`_10_audio_classification/`](_10_audio_classification/): clip-level labels (language, speaker, emotion, genre).
- [`_11_audio_transcription/`](_11_audio_transcription/): speech-to-text with optional diarization and timestamps.
- [`_12_audio_extraction/`](_12_audio_extraction/): call or meeting recording into a typed object (action items, attendees, decisions).

### Video
- [`_13_video_classification/`](_13_video_classification/): clip-level labels.
- [`_14_video_extraction/`](_14_video_extraction/): events, scene descriptions, action timestamps.

### Document
- [`_15_document_classification/`](_15_document_classification/): invoice, receipt, contract, spec sheet.
- [`_16_document_extraction/`](_16_document_extraction/): multipage PDF into a typed object, with line items where relevant.

### Composed patterns
These layer on top of any modality.
- [`_17_llm_as_judge/`](_17_llm_as_judge/): score outputs against a rubric. The same machinery as labeling, repurposed for evals.
- [`_18_quality_review/`](_18_quality_review/): labeler, reviewer, adjudicator pipeline applied on top of an extraction primitive.
- [`_19_inter_annotator_agreement/`](_19_inter_annotator_agreement/): raw agreement, Fleiss' kappa, Krippendorff's alpha, and pairwise Cohen's kappa over agent labelers and jury votes, with low-agreement items routed to review.

### Synthetic data generation
These emit training data (JSONL with per-row provenance; filtered files print kept/dropped counts) rather than labels.
- [`_20_instruction_generation/`](_20_instruction_generation/): self-instruct from seeds, typed Evol-Instruct operators, and a topic-tree pipeline emitting SFT chat rows.
- [`_21_rejection_sampling/`](_21_rejection_sampling/): sample K solutions and keep what a programmatic verifier or judge accepts - verified reasoning traces, best-of-n for non-verifiable prompts, and RL prompt selection by pass rate.
- [`_22_dataset_curation/`](_22_dataset_curation/): the filters - judge quality-gate over JSONL, pure-stdlib MinHash near-dedup, and 13-gram benchmark decontamination.
- [`_23_critique_and_revision/`](_23_critique_and_revision/): constitutional-AI-style draft, critique against a written principle, revise - SFT rows with critique provenance, plus (chosen, rejected) pairs in the exact shape the `_05` jury consumes.
- [`_24_persona_driven_generation/`](_24_persona_driven_generation/): typed personas condition prompt and gold-answer problem generation, with a measured (not asserted) diversity report.
- [`_25_tool_call_trajectories/`](_25_tool_call_trajectories/): function-calling SFT data validated against real agno tool schemas, multi-turn user-sim vs tool-executing assistant rollouts, and a judge filter keeping successful trajectories.

### Scale and safety
- [`_26_scale_out/`](_26_scale_out/): the N=100k mechanics every other folder inherits - async fan-out with bounded concurrency and measured speedup, checkpointed resume by row id, and token/cost accounting with batch-tier projections.
- [`_27_safety_labeling/`](_27_safety_labeling/): policy-taxonomy classification with escalation, over-refusal preference pairs in the `_05` jury shape, and a persona-generated boundary-probe eval set with a content screen.

## Running a cookbook

From the agno repo root, create and activate the demo venv:

```bash
./scripts/demo_setup.sh
```

```bash
source .venvs/demo/bin/activate
```

```bash
python cookbook/data_labeling/_01_text_classification/basic.py
```

Each subfolder's `README.md` documents its inputs, the model it expects, and any extra dependencies.

| Variable | Used by |
|---|---|
| `GOOGLE_API_KEY` | Default for every cookbook (Gemini 3.5 Flash, natively multimodal) |
| `ANTHROPIC_API_KEY` | `_18_quality_review/` (Claude is the second labeler) and the `_05_text_pairwise_preference/` jury files (`dpo_jury.py`, `jury_calibrated.py`, `jury_hardened.py`) |
| `OPENAI_API_KEY` | The `_05_text_pairwise_preference/` jury files |
| `GROQ_API_KEY`, `MISTRAL_API_KEY` | `_05_text_pairwise_preference/dpo_jury.py` only — the 5-model jury |

The per-cookbook README calls out which model it uses and why.
