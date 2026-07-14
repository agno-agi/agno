"""
Settings
========

Shared runtime objects. Keep model ids in one place.
"""

from pathlib import Path

from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses
from agno.tools.file_generation import FileGenerationTools


def default_model() -> OpenAIResponses:
    """Top-level agent model."""
    return OpenAIResponses(id="gpt-5.5")


def sub_agent_model() -> OpenAIResponses:
    """Model for the context-provider sub-agents (read/write tool-routing work)."""
    return OpenAIResponses(id="gpt-5.5")


def judge_model() -> OpenAIResponses:
    """Model for the eval LLM judge (AgentAsJudgeEval).

    Pinned here so the eval suite is reliable: the library default is a
    smaller model whose verdicts on these rubrics are noticeably flakier.
    """
    return OpenAIResponses(id="gpt-5.5")


def gemini_flash() -> Gemini:
    """Gemini 3.5 Flash — swap in per agent for heavier multimodal (audio, video)
    when its quota allows."""
    return Gemini(id="gemini-3.5-flash")


# Where generated HTML pages are saved (under data/, gitignored).
_GENERATED_DIR = Path(__file__).parent / "data" / "generated"


def html_tools() -> FileGenerationTools:
    """HTML-only file generation, shared by the wiki agents.

    Lets a wiki agent emit a downloadable, self-contained HTML page (for
    example, rendering a wiki page as a standalone web page). The file is
    returned as an artifact on the response and saved under data/generated/.
    HTML only — the other formats stay off so the agent sees a single
    generate_html_file tool.
    """
    return FileGenerationTools(
        enable_json_generation=False,
        enable_csv_generation=False,
        enable_pdf_generation=False,
        enable_docx_generation=False,
        enable_txt_generation=False,
        enable_html_generation=True,
        output_directory=str(_GENERATED_DIR),
    )
