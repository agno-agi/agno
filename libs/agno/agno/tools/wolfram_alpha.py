import json
import urllib.error
import urllib.parse
import urllib.request
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import wolframalpha
except ImportError:
    raise ImportError("`wolframalpha` not installed. Please install using `pip install wolframalpha`")


class WolframAlphaTools(Toolkit):
    def __init__(
        self,
        app_id: Optional[str] = None,
        max_pods: int = 10,
        include_pod_ids: Optional[List[str]] = None,
        enable_query: bool = True,
        enable_short_answer: bool = True,
        enable_conversational: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        self.app_id = app_id or getenv("WOLFRAM_ALPHA_APP_ID")
        if not self.app_id:
            raise ValueError(
                "Wolfram Alpha App ID not provided. "
                "Set WOLFRAM_ALPHA_APP_ID environment variable or pass app_id parameter. "
                "Get one at https://developer.wolframalpha.com/"
            )

        self.client = wolframalpha.Client(self.app_id)
        self.max_pods = max_pods
        self.include_pod_ids = include_pod_ids

        tools: List[Any] = []
        if all or enable_query:
            tools.append(self.query)
        if all or enable_short_answer:
            tools.append(self.short_answer)
        if all or enable_conversational:
            tools.append(self.conversational_query)

        super().__init__(name="wolfram_alpha_tools", tools=tools, **kwargs)

    def query(self, input_query: str) -> str:
        """Query Wolfram Alpha and return structured pod results.

        Args:
            input_query: Natural language or mathematical expression.

        Returns:
            str: JSON with pods containing computed results.
        """
        try:
            res = self.client.query(input_query)

            if not hasattr(res, "pods") or res.pods is None:
                return json.dumps({"success": False, "error": "No results found.", "query": input_query})

            pods = []
            pod_count = 0
            for pod in res.pods:
                if pod_count >= self.max_pods:
                    break
                if self.include_pod_ids and pod.id not in self.include_pod_ids:
                    continue

                texts = []
                if hasattr(pod, "subpods"):
                    for subpod in pod.subpods:
                        if hasattr(subpod, "plaintext") and subpod.plaintext:
                            texts.append(subpod.plaintext)
                elif hasattr(pod, "text") and pod.text:
                    texts.append(pod.text)

                if texts:
                    pods.append({"title": pod.title, "id": pod.id, "text": "\n".join(texts)})
                    pod_count += 1

            if not pods:
                return json.dumps({"success": False, "error": "No text results produced.", "query": input_query})

            return json.dumps({"success": True, "query": input_query, "num_pods": len(pods), "pods": pods})

        except Exception as e:
            logger.exception(f"Error querying Wolfram Alpha: {input_query}")
            return json.dumps({"success": False, "error": str(e), "query": input_query})

    def short_answer(self, input_query: str) -> str:
        """Get a single-line answer from Wolfram Alpha Short Answers API.

        Args:
            input_query: Natural language question.

        Returns:
            str: JSON with the answer string.
        """
        try:
            encoded_query = urllib.parse.quote_plus(input_query)
            url = f"https://api.wolframalpha.com/v1/result?appid={self.app_id}&i={encoded_query}"

            with urllib.request.urlopen(url, timeout=10) as response:
                answer = response.read().decode("utf-8")

            return json.dumps({"success": True, "query": input_query, "answer": answer})

        except urllib.error.HTTPError as e:
            error_msg = "Query not understood" if e.code == 501 else str(e)
            return json.dumps({"success": False, "query": input_query, "error": error_msg})
        except Exception as e:
            logger.exception(f"Error getting short answer: {input_query}")
            return json.dumps({"success": False, "error": str(e), "query": input_query})

    def conversational_query(self, input_query: str, conversation_id: Optional[str] = None) -> str:
        """Query Wolfram Alpha Conversational API. Supports follow-up questions.

        Args:
            input_query: Natural language question.
            conversation_id: ID from previous response to continue conversation.

        Returns:
            str: JSON with answer and conversation_id for follow-ups.
        """
        try:
            encoded_query = urllib.parse.quote_plus(input_query)
            url = f"https://api.wolframalpha.com/v1/conversation.jsp?appid={self.app_id}&i={encoded_query}"
            if conversation_id:
                url += f"&conversationid={conversation_id}"

            with urllib.request.urlopen(url, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))

            return json.dumps(
                {
                    "success": True,
                    "query": input_query,
                    "answer": result.get("result", ""),
                    "conversation_id": result.get("conversationID", ""),
                }
            )

        except Exception as e:
            logger.exception(f"Error in conversational query: {input_query}")
            return json.dumps({"success": False, "error": str(e), "query": input_query})
