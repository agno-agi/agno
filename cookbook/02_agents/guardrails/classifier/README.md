# Classifier Guardrail

Examples of using ClassifierGuardrail to classify and filter content using LLM-based or ML-based models. Supports OpenAI, sklearn, transformers, and ONNX backends.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via `direnv allow`.
- Use `.venvs/demo/bin/python` to run cookbook examples.
- Some examples require additional packages (scikit-learn, transformers, onnxruntime) as noted in file docstrings.

## Files

- dry_run.py - Log classifications without blocking.
- on_fail.py - Custom callback when classification blocks content.
- sklearn_model.py - Classifier with sklearn backend for fast offline classification.
- transformers_model.py - Classifier with HuggingFace transformers backend.
- onnx_model.py - Classifier with ONNX backend for optimized inference.
- train_sklearn_model.py - Train a simple sklearn spam classifier for demos.
