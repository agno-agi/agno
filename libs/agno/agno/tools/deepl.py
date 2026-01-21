"""DeepL Tools for translating text between languages.

This toolkit provides AI agents with the ability to translate text using
the DeepL API, which offers high-quality neural machine translation.

Get your free API key at: https://www.deepl.com/pro-api
"""

import json
from os import getenv
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class DeepLTools(Toolkit):
    """A toolkit for translating text using the DeepL API.

    DeepL provides high-quality neural machine translation supporting 30+
    languages. This toolkit enables AI agents to:
    - Translate text between languages
    - Get supported source and target languages
    - Check API usage statistics

    Example:
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        from agno.tools.deepl import DeepLTools

        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[DeepLTools()],
        )
        agent.print_response("Translate 'Hello, world!' to German")
        ```
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_translate_text: bool = True,
        enable_get_supported_languages: bool = True,
        enable_get_usage: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        """Initialize the DeepL toolkit.

        Args:
            api_key: DeepL API key. If not provided, will look for
                DEEPL_API_KEY environment variable.
            enable_translate_text: Enable the translate_text tool. Default: True.
            enable_get_supported_languages: Enable the get_supported_languages tool. Default: True.
            enable_get_usage: Enable the get_usage tool. Default: False.
            all: Enable all tools. Default: False.
            **kwargs: Additional arguments passed to the Toolkit base class.
        """
        self.api_key = api_key or getenv("DEEPL_API_KEY")
        if not self.api_key:
            logger.warning("No DeepL API key provided. Set DEEPL_API_KEY environment variable.")

        # Determine API base URL based on key type (free keys end with ":fx")
        if self.api_key and self.api_key.endswith(":fx"):
            self.base_url = "https://api-free.deepl.com"
        else:
            self.base_url = "https://api.deepl.com"

        tools: List[Any] = []
        if all or enable_translate_text:
            tools.append(self.translate_text)
        if all or enable_get_supported_languages:
            tools.append(self.get_supported_languages)
        if all or enable_get_usage:
            tools.append(self.get_usage)

        super().__init__(name="deepl_tools", tools=tools, **kwargs)

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated request to the DeepL API.

        Args:
            endpoint: API endpoint path (e.g., "/v2/translate").
            method: HTTP method (GET or POST).
            params: Optional query parameters for GET requests.
            data: Optional JSON body for POST requests.

        Returns:
            JSON response as a dictionary or list.

        Raises:
            Exception: If the API request fails.
        """
        url = f"{self.base_url}{endpoint}"
        if params:
            url = f"{url}?{urlencode(params)}"

        headers = {
            "Authorization": f"DeepL-Auth-Key {self.api_key}",
            "Content-Type": "application/json",
        }

        request_data = None
        if data:
            request_data = json.dumps(data).encode("utf-8")

        request = Request(url, data=request_data, headers=headers, method=method)
        with urlopen(request) as response:
            return json.loads(response.read().decode())

    def translate_text(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        formality: Optional[str] = None,
        context: Optional[str] = None,
    ) -> str:
        """Translate text to a target language using DeepL.

        Args:
            text: The text to translate.
            target_lang: Target language code (e.g., "DE" for German, "FR" for French,
                "ES" for Spanish, "JA" for Japanese). Use get_supported_languages
                to see all available target languages.
            source_lang: Optional source language code. If not provided, DeepL will
                auto-detect the source language.
            formality: Optional formality preference. Options are:
                - "default": Default formality
                - "more": More formal language
                - "less": Less formal language
                - "prefer_more": Prefer more formal, fallback to default
                - "prefer_less": Prefer less formal, fallback to default
                Note: Not all languages support formality (e.g., German, Spanish do;
                English does not).
            context: Optional context to improve translation accuracy. Provide a few
                sentences in the same language as the source text to help DeepL
                understand the meaning.

        Returns:
            JSON string containing the translation result with detected source
            language and translated text.
        """
        if not self.api_key:
            return "Error: No DeepL API key provided. Set DEEPL_API_KEY environment variable."

        if not text:
            return "Error: Please provide text to translate."

        if not target_lang:
            return "Error: Please provide a target language code."

        log_debug(f"Translating text to {target_lang}")

        try:
            request_data: Dict[str, Any] = {
                "text": [text],
                "target_lang": target_lang.upper(),
            }

            if source_lang:
                request_data["source_lang"] = source_lang.upper()

            if formality and formality in [
                "default",
                "more",
                "less",
                "prefer_more",
                "prefer_less",
            ]:
                request_data["formality"] = formality

            if context:
                request_data["context"] = context

            response = self._make_request("/v2/translate", method="POST", data=request_data)

            translations = response.get("translations", [])
            if translations:
                result = {
                    "detected_source_language": translations[0].get("detected_source_language"),
                    "text": translations[0].get("text"),
                }
                return json.dumps(result, indent=2)
            else:
                return "Error: No translation returned from API."

        except Exception as e:
            return f"Error translating text: {e}"

    def get_supported_languages(self, language_type: str = "target") -> str:
        """Get the list of languages supported by DeepL.

        Args:
            language_type: Type of languages to retrieve. Options are:
                - "source": Languages that can be used as source language
                - "target": Languages that can be used as target language (default)

        Returns:
            JSON string containing list of supported languages with their codes,
            names, and whether they support formality options.
        """
        if not self.api_key:
            return "Error: No DeepL API key provided. Set DEEPL_API_KEY environment variable."

        log_debug(f"Getting supported {language_type} languages")

        try:
            params = {"type": language_type}
            response = self._make_request("/v2/languages", params=params)

            languages = [
                {
                    "code": lang.get("language"),
                    "name": lang.get("name"),
                    "supports_formality": lang.get("supports_formality", False),
                }
                for lang in response
            ]

            return json.dumps({"languages": languages}, indent=2)

        except Exception as e:
            return f"Error getting supported languages: {e}"

    def get_usage(self) -> str:
        """Get the current API usage statistics.

        Returns:
            JSON string containing usage information including character count
            and limit for the current billing period.
        """
        if not self.api_key:
            return "Error: No DeepL API key provided. Set DEEPL_API_KEY environment variable."

        log_debug("Getting API usage statistics")

        try:
            response = self._make_request("/v2/usage")

            result = {
                "character_count": response.get("character_count"),
                "character_limit": response.get("character_limit"),
            }

            # Calculate percentage used if both values are present
            if result["character_count"] is not None and result["character_limit"]:
                percentage = (result["character_count"] / result["character_limit"]) * 100
                result["percentage_used"] = round(percentage, 2)

            return json.dumps(result, indent=2)

        except Exception as e:
            return f"Error getting usage: {e}"
