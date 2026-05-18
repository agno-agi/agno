# Data labeling

End-to-end examples for data classification and labeling using agents.

Each subfolder holds examples for one theme, containing a `basic.py` that runs end-to-end, plus variants that add task-meaningful options on top.

Workflows are organized by modality (text, image, audio, video, document) and output shape (classify, extract, rank, span-label). Two further patterns (`llm_as_judge`, `quality_review`) compose on top of any of these.

Start with [`text_classification/basic.py`](text_classification/basic.py). Every other cookbook mirrors its structure.

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
- [`text_classification/`](text_classification/): assign one of N labels (sentiment, intent, topic).
- [`text_multilabel_classification/`](text_multilabel_classification/): assign any subset of N tags, optionally hierarchical.
- [`text_extraction/`](text_extraction/): text into a typed Pydantic object (entities, fields, nested structures).
- [`text_span_labeling/`](text_span_labeling/): mark character or token spans (NER, PII detection, claim and evidence highlighting).
- [`text_pairwise_preference/`](text_pairwise_preference/): rank A vs B against a rubric (RLHF data shape).

### Image
- [`image_classification/`](image_classification/): single or multi-label per image.
- [`image_extraction/`](image_extraction/): image into a typed object (attributes, OCR fields, captions).
- [`image_extraction_to_vectordb/`](image_extraction_to_vectordb/): extract, embed, and store for similarity search.
- [`image_bounding_boxes/`](image_bounding_boxes/): region detection with `(x, y, w, h)` per object.

### Audio
- [`audio_classification/`](audio_classification/): clip-level labels (language, speaker, emotion, genre).
- [`audio_transcription/`](audio_transcription/): speech-to-text with optional diarization and timestamps.
- [`audio_extraction/`](audio_extraction/): call or meeting recording into a typed object (action items, attendees, decisions).

### Video
- [`video_classification/`](video_classification/): clip-level labels.
- [`video_extraction/`](video_extraction/): events, scene descriptions, action timestamps.

### Document
- [`document_classification/`](document_classification/): invoice, receipt, contract, spec sheet.
- [`document_extraction/`](document_extraction/): multipage PDF into a typed object, with line items where relevant.

### Composed patterns
These layer on top of any modality.
- [`llm_as_judge/`](llm_as_judge/): score outputs against a rubric. The same machinery as labeling, repurposed for evals.
- [`quality_review/`](quality_review/): labeler, reviewer, adjudicator pipeline applied on top of an extraction primitive.

## Running a cookbook

From the agno repo root, create and activate the demo venv:

```bash
./scripts/demo_setup.sh
```

```bash
source .venvs/demo/bin/activate
```

```bash
python cookbook/data_labeling/text_classification/basic.py
```

Each subfolder's `README.md` documents its inputs, the model it expects, and any extra dependencies.

| Variable | Used by |
|---|---|
| `OPENAI_API_KEY` | Default for text and most extraction cookbooks |
| `ANTHROPIC_API_KEY` | Image and document cookbooks where Claude is the picked model |
| `GOOGLE_API_KEY` | Audio and video cookbooks (Gemini) |

The per-cookbook README calls out which model it uses and why.
