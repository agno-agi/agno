from agno.agent import Agent
from agno.tools.docling import DoclingTools
from paths import (
    audio_video_path,
    docx_path,
    html_path,
    image_path,
    md_path,
    pdf_path,
    pptx_path,
    xlsx_path,
    xml_path,
)


def run_basic_examples() -> None:
    agent = Agent(
        tools=[DoclingTools(all=True)],
        description="You are an agent that converts documents from all Docling parsers and exports to all supported output formats.",
    )

    agent.print_response(
        "List supported Docling input parsers and active allowed parsers.",
        markdown=True,
    )

    agent.print_response(
        f"Convert to Markdown: {pdf_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to JSON and return the full JSON without summarizing: {pdf_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to YAML: {pdf_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to DocTags: {pdf_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to VTT: {pdf_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to HTML split page: {pdf_path}",
        markdown=True,
    )

    # Additional parser examples based on static resources.
    agent.print_response(
        f"Convert to Markdown: {docx_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to Markdown: {md_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to Markdown: {html_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to Markdown: {xml_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to Markdown: {xlsx_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to Markdown: {pptx_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to Markdown: {image_path}",
        markdown=True,
    )
    agent.print_response(
        f"Convert to VTT: {audio_video_path}",
        markdown=True,
    )

    # convert_string is limited by Docling to Markdown and HTML source content.
    agent.print_response(
        "Use convert_string_content to convert this markdown string to JSON: # Inline Markdown\n\nThis is a parser test.",
        markdown=True,
    )
    agent.print_response(
        "Use convert_string_content to convert this html string to Markdown: <h1>Inline HTML</h1><p>This is a parser test.</p>",
        markdown=True,
    )
