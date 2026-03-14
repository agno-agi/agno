from pathlib import Path
from typing import Any, List, Literal, Optional, Union

from agno.exceptions import CheckTrigger, InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail, OnFailCallback
from agno.models.message import Message
from agno.run.agent import RunInput, RunOutput
from agno.run.messages import RunMessages
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.utils.guardrails import extract_all_text_from_run_messages
from agno.utils.log import log_debug


class ClassifierGuardrail(BaseGuardrail):
    """Guardrail that classifies content against custom categories using LLM, sklearn, transformers, or ONNX."""

    DEFAULT_CLASSIFICATION_PROMPT = """Classify the following content into exactly one of these categories: {categories}

Content to classify:
{content}

Respond with ONLY the category name, nothing else."""

    def __init__(
        self,
        model: Any,
        model_type: Literal["llm", "sklearn", "transformers", "onnx"] = "llm",
        categories: Optional[List[str]] = None,
        blocked_categories: Optional[List[str]] = None,
        classification_prompt: Optional[str] = None,
        vectorizer_path: Optional[Union[str, Path]] = None,
        device: Literal["cpu", "cuda", "auto"] = "auto",
        max_length: Optional[int] = None,
        check_output: bool = False,
        dry_run: bool = False,
        on_fail: Optional[OnFailCallback] = None,
    ):
        """Initialize a new ClassifierGuardrail.

        Args:
            model: Classification model. Agno Model for llm, file path for sklearn/onnx,
                   or HuggingFace model ID for transformers.
            model_type: Backend type. One of "llm", "sklearn", "transformers", "onnx".
            categories: Category names to classify against.
            blocked_categories: Categories that trigger a block. Defaults to all except "safe".
            classification_prompt: Custom prompt template for LLM. Use {content} and {categories}.
            vectorizer_path: Path to sklearn/onnx vectorizer file.
            device: Device for transformers/onnx. "cpu", "cuda", or "auto".
            max_length: Max input length in characters. None means no truncation.
            check_output: Whether to also check output in post_check.
            dry_run: If True, logs violations without raising errors.
            on_fail: Optional callback invoked when a check fails.
                     Receives (error, input_data, context).
        """
        super().__init__(dry_run=dry_run, on_fail=on_fail)
        self.model = model
        self.model_type = model_type
        self.categories = categories or []
        self.check_output = check_output
        self.classification_prompt = classification_prompt or self.DEFAULT_CLASSIFICATION_PROMPT
        self.vectorizer_path = Path(vectorizer_path) if vectorizer_path else None
        self.device = device
        self.max_length = max_length

        # Lazy-loaded model objects for sklearn/transformers/onnx
        self._loaded_model: Any = None
        self._loaded_vectorizer: Any = None
        self._loaded_pipeline: Any = None
        self._loaded_session: Any = None  # ONNX

        # Default: block everything except "safe" if not specified
        if blocked_categories is not None:
            self.blocked_categories = blocked_categories
        else:
            self.blocked_categories = [cat for cat in self.categories if cat.lower() != "safe"]

        # Validate blocked_categories are in categories (only for llm where categories are explicit)
        if self.categories:
            for blocked in self.blocked_categories:
                if blocked not in self.categories:
                    raise ValueError(f"Blocked category '{blocked}' not found in categories list")

    # =========================================================================
    # Truncation
    # =========================================================================

    def _truncate(self, content: str) -> str:
        """Truncate content to max_length if set."""
        if self.max_length and len(content) > self.max_length:
            return content[: self.max_length]
        return content

    # =========================================================================
    # LLM Backend
    # =========================================================================

    def _build_prompt(self, content: str) -> str:
        """Build the classification prompt with content and categories."""
        categories_str = ", ".join(self.categories)
        return self.classification_prompt.format(content=content, categories=categories_str)

    def _classify_llm_sync(self, content: str) -> str:
        """Classify content synchronously using an Agno Model."""
        prompt = self._build_prompt(content)
        messages = [Message(role="user", content=prompt)]
        response = self.model.response(messages=messages)

        if response.content:
            classification = response.content.strip().lower()
            for category in self.categories:
                if category.lower() == classification:
                    return category
            return response.content.strip()
        return "unknown"

    async def _classify_llm_async(self, content: str) -> str:
        """Classify content asynchronously using an Agno Model."""
        prompt = self._build_prompt(content)
        messages = [Message(role="user", content=prompt)]
        response = await self.model.aresponse(messages=messages)

        if response.content:
            classification = response.content.strip().lower()
            for category in self.categories:
                if category.lower() == classification:
                    return category
            return response.content.strip()
        return "unknown"

    # =========================================================================
    # sklearn Backend
    # =========================================================================

    def _load_sklearn_model(self) -> None:
        """Lazy-load sklearn model and optional vectorizer from disk."""
        if self._loaded_model is not None:
            return

        try:
            import joblib  # type: ignore[import-not-found,import-untyped]
        except ImportError:
            raise ImportError("`joblib` not installed. Install with: pip install joblib scikit-learn")

        model_path = Path(self.model)
        if not model_path.exists():
            raise FileNotFoundError(f"sklearn model not found: {model_path}")

        log_debug(f"Loading sklearn model from {model_path}")
        self._loaded_model = joblib.load(model_path)

        if self.vectorizer_path and self.vectorizer_path.exists():
            log_debug(f"Loading vectorizer from {self.vectorizer_path}")
            self._loaded_vectorizer = joblib.load(self.vectorizer_path)

    def _classify_sklearn(self, content: str) -> str:
        """Classify content using a scikit-learn model."""
        self._load_sklearn_model()

        if self._loaded_vectorizer:
            features = self._loaded_vectorizer.transform([content])
            prediction = self._loaded_model.predict(features)
        else:
            prediction = self._loaded_model.predict([content])

        label = str(prediction[0]) if hasattr(prediction, "__iter__") else str(prediction)
        return label

    # =========================================================================
    # Transformers Backend
    # =========================================================================

    def _load_transformers_model(self) -> None:
        """Lazy-load HuggingFace Transformers pipeline."""
        if self._loaded_pipeline is not None:
            return

        try:
            from transformers import pipeline  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError("`transformers` not installed. Install with: pip install transformers torch")

        if self.device == "auto":
            device_id = 0
        elif self.device == "cpu":
            device_id = -1
        else:
            device_id = 0

        log_debug(f"Loading transformers model: {self.model}")
        self._loaded_pipeline = pipeline("text-classification", model=str(self.model), device=device_id, framework="pt")

    def _classify_transformers(self, content: str) -> str:
        """Classify content using a HuggingFace Transformers model."""
        self._load_transformers_model()

        result = self._loaded_pipeline(content)
        if isinstance(result, list):
            result = result[0]

        return str(result["label"])

    # =========================================================================
    # ONNX Backend
    # =========================================================================

    def _load_onnx_model(self) -> None:
        """Lazy-load ONNX Runtime session."""
        if self._loaded_session is not None:
            return

        try:
            import onnxruntime as ort  # type: ignore[import-not-found,import-untyped]
        except ImportError:
            raise ImportError("`onnxruntime` not installed. Install with: pip install onnxruntime")

        model_path = Path(self.model)
        if not model_path.exists():
            raise FileNotFoundError(f"ONNX model not found: {model_path}")

        log_debug(f"Loading ONNX model from {model_path}")
        self._loaded_session = ort.InferenceSession(str(model_path))

        if self.vectorizer_path and self.vectorizer_path.exists():
            try:
                import joblib  # type: ignore[import-not-found,import-untyped]

                log_debug(f"Loading vectorizer from {self.vectorizer_path}")
                self._loaded_vectorizer = joblib.load(self.vectorizer_path)
            except ImportError:
                raise ImportError("`joblib` not installed. Install with: pip install joblib")

    def _classify_onnx(self, content: str) -> str:
        """Classify content using an ONNX model."""
        import numpy as np  # type: ignore[import-not-found]

        self._load_onnx_model()

        if self._loaded_vectorizer:
            features = self._loaded_vectorizer.transform([content]).toarray().astype(np.float32)
        else:
            raise ValueError("ONNX models require a vectorizer_path to convert text to features")

        input_name = self._loaded_session.get_inputs()[0].name
        result = self._loaded_session.run(None, {input_name: features})

        # result[0] is typically the prediction array
        prediction = result[0]
        label = str(prediction[0]) if hasattr(prediction, "__iter__") else str(prediction)
        return label

    # =========================================================================
    # Dispatch
    # =========================================================================

    def _classify_sync(self, content: str) -> str:
        """Route classification to the appropriate backend."""
        content = self._truncate(content)

        if self.model_type == "sklearn":
            return self._classify_sklearn(content)
        elif self.model_type == "transformers":
            return self._classify_transformers(content)
        elif self.model_type == "onnx":
            return self._classify_onnx(content)
        else:
            return self._classify_llm_sync(content)

    async def _classify_async(self, content: str) -> str:
        """Route async classification to the appropriate backend.

        sklearn, transformers, and onnx are sync-only (CPU-bound), so they
        delegate to their sync implementations. LLM uses true async.
        """
        content = self._truncate(content)

        if self.model_type == "sklearn":
            return self._classify_sklearn(content)
        elif self.model_type == "transformers":
            return self._classify_transformers(content)
        elif self.model_type == "onnx":
            return self._classify_onnx(content)
        else:
            return await self._classify_llm_async(content)

    # =========================================================================
    # Violation Handling
    # =========================================================================

    def _check_classification(
        self,
        classification: str,
        content_type: Literal["input", "output"],
        check_type: str,
        input_data: Any = None,
    ) -> None:
        """Check if the classification is in blocked categories and handle violation."""
        if classification in self.blocked_categories:
            additional_data = {
                "classification": classification,
                "blocked_categories": self.blocked_categories,
                "content_type": content_type,
            }

            error: Union[InputCheckError, OutputCheckError]
            if content_type == "output":
                error = OutputCheckError(
                    f"Content classified as blocked category: {classification}",
                    additional_data=additional_data,
                    check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
                )
            else:
                error = InputCheckError(
                    f"Content classified as blocked category: {classification}",
                    additional_data=additional_data,
                    check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
                )

            self._handle_violation(
                error,
                "ClassifierGuardrail",
                check_type,
                f"classification={classification}",
                input_data=input_data,
            )

    # =========================================================================
    # Hook Methods
    # =========================================================================

    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Classify input content and block if it matches a blocked category."""
        content = run_input.input_content_string()
        if not content.strip():
            return

        classification = self._classify_sync(content)
        self._check_classification(classification, "input", "pre_check", input_data=run_input)

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Async classify input content and block if it matches a blocked category."""
        content = run_input.input_content_string()
        if not content.strip():
            return

        classification = await self._classify_async(content)
        self._check_classification(classification, "input", "async_pre_check", input_data=run_input)

    def model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Classify all messages in RunMessages before model processing."""
        content = extract_all_text_from_run_messages(run_messages)
        if not content.strip():
            return

        classification = self._classify_sync(content)
        self._check_classification(classification, "input", "model_check", input_data=run_messages)

    async def async_model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Async classify all messages before model processing."""
        content = extract_all_text_from_run_messages(run_messages)
        if not content.strip():
            return

        classification = await self._classify_async(content)
        self._check_classification(classification, "input", "async_model_check", input_data=run_messages)

    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Classify output content if check_output is enabled."""
        if not self.check_output:
            return

        content = str(run_output.content) if run_output.content else ""
        if not content.strip():
            return

        classification = self._classify_sync(content)
        self._check_classification(classification, "output", "post_check", input_data=run_output)

    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Async classify output content if check_output is enabled."""
        if not self.check_output:
            return

        content = str(run_output.content) if run_output.content else ""
        if not content.strip():
            return

        classification = await self._classify_async(content)
        self._check_classification(classification, "output", "async_post_check", input_data=run_output)
