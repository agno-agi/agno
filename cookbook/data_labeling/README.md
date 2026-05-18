# Data labeling

End-to-end examples for data classification and labeling using agents.

Each subfolder holds examples for one theme, containing a `basic.py` that runs end-to-end, plus variants that add task-meaningful options on top.

Workflows are organized by modality (text, image, audio, video, document) and output shape (classify, extract, rank, span-label). Two further patterns (`_17_llm_as_judge`, `_18_quality_review`) compose on top of any of these.

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
| `OPENAI_API_KEY` | Default for text and most extraction cookbooks |
| `ANTHROPIC_API_KEY` | Image and document cookbooks where Claude is the picked model |
| `GOOGLE_API_KEY` | Audio and video cookbooks (Gemini) |

The per-cookbook README calls out which model it uses and why.
