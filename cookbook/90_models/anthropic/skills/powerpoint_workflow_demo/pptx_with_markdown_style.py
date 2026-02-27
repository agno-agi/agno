"""
PPTX Agent with Markdown-Injected Template Styling.

This script demonstrates a different approach to template-guided PPTX generation:
instead of post-processing a generated PPTX with python-pptx, it extracts the
template's styling guide as markdown text and injects it directly into Claude's
system instructions. Claude then applies those styles while writing the PptxGenJS code.

Workflow:
1. Parse the PPTX template and convert its styling into a markdown guide
2. Inject the markdown guide into the agent's system instructions (not user prompt)
3. Create an Agno Agent with pptx skill
4. Run the agent with a short, imperative user message
5. Extract generated file IDs from the response
6. Download the final PPTX

Key design choice: styling guide → system instructions (not user message)
----------------------------------------------------------------------
Placing the styling guide in system instructions (not the user message) prevents
Claude from treating it as a document to acknowledge. When injected into the user
message, Claude reads the large markdown block, says "Now I have all the info I
need. Let me create the PptxGenJS script..." -- and then returns a text-only
planning response without ever invoking code_execution.

By placing it in system instructions, Claude treats the styling guide as background
context and immediately executes the task when given a short, imperative prompt.

Contrast with simple_pptx_two_skills.py:
- That script: uploads template binary -> Claude applies style via post-processing
- This script: converts template to human-readable markdown -> Claude applies
  style directly in its PptxGenJS code, no post-processing needed

Prerequisites:
    pip install agno anthropic python-pptx lxml
    export ANTHROPIC_API_KEY="your_api_key_here"

Usage:
    .venvs/demo/bin/python \\
        cookbook/90_models/anthropic/skills/powerpoint_workflow_demo/pptx_with_markdown_style.py

    .venvs/demo/bin/python \\
        cookbook/90_models/anthropic/skills/powerpoint_workflow_demo/pptx_with_markdown_style.py \\
        --template my_template.pptx \\
        --output styled_output.pptx \\
        --prompt "Create a 5-slide product roadmap presentation" \\
        --debug
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
from anthropic import Anthropic

from file_download_helper import download_skill_files
from template_to_markdown import extract_template_to_markdown

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File ID extraction
# ---------------------------------------------------------------------------


def extract_file_ids(response, debug: bool = False) -> list[str]:
    """Extract generated file IDs from an Agno RunResponse.

    Checks three locations in priority order:
    1. response.extra_data["file_ids"]
    2. response.provider_data["file_ids"]
    3. Each message's provider_data["file_ids"]

    The Anthropic Claude model stores file IDs in provider_data on messages
    after _parse_provider_response() processes bash_code_execution_tool_result
    blocks (see libs/agno/agno/models/anthropic/claude.py:934).

    Args:
        response: The RunResponse object returned by agent.run().
        debug: If True, log detailed response structure information.

    Returns:
        List of file ID strings (may be empty).
    """
    if debug:
        logger.debug("=== extract_file_ids: inspecting response ===")
        logger.debug("Response type: %s", type(response).__name__)
        attrs = [a for a in dir(response) if not a.startswith("_")]
        logger.debug("Response public attributes: %s", attrs)
        if hasattr(response, "extra_data"):
            logger.debug("response.extra_data: %s", response.extra_data)
        if hasattr(response, "provider_data"):
            logger.debug("response.provider_data: %s", response.provider_data)
        if hasattr(response, "messages"):
            msg_count = len(response.messages) if response.messages else 0
            logger.debug("Message count: %d", msg_count)
            if response.messages:
                for i, msg in enumerate(response.messages):
                    logger.debug(
                        "  Message %d: type=%s role=%s",
                        i,
                        type(msg).__name__,
                        getattr(msg, "role", "N/A"),
                    )
                    logger.debug(
                        "  Message %d provider_data: %s",
                        i,
                        getattr(msg, "provider_data", None),
                    )
                    logger.debug(
                        "  Message %d extra_data: %s",
                        i,
                        getattr(msg, "extra_data", None),
                    )

    file_ids: list[str] = []

    if hasattr(response, "extra_data") and isinstance(response.extra_data, dict):
        ids = response.extra_data.get("file_ids", [])
        if ids:
            if debug:
                logger.debug("Found file_ids in response.extra_data: %s", ids)
            file_ids = ids

    if not file_ids and hasattr(response, "provider_data") and isinstance(response.provider_data, dict):
        ids = response.provider_data.get("file_ids", [])
        if ids:
            if debug:
                logger.debug("Found file_ids in response.provider_data: %s", ids)
            file_ids = ids

    if not file_ids and response.messages:
        for msg in response.messages:
            if hasattr(msg, "provider_data") and isinstance(msg.provider_data, dict):
                ids = msg.provider_data.get("file_ids", [])
                if ids:
                    if debug:
                        logger.debug(
                            "Found file_ids in message.provider_data (role=%s): %s",
                            getattr(msg, "role", "?"),
                            ids,
                        )
                    file_ids.extend(ids)

    if debug:
        logger.debug("Total file_ids extracted: %s", file_ids)

    return file_ids


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------


def run_workflow(template_path: Path, user_prompt: str, output_path: Path, debug: bool = False) -> None:
    """Execute the markdown-style injection workflow.

    Steps:
    1. Extract template styling as markdown
    2. Create agent with styling guide in system instructions (not user message)
    3. Run agent with short, imperative user message
    4. Extract generated file IDs
    5. Download generated files

    Why styling guide goes in system instructions:
        When a ~6000-char markdown document is embedded in the user message (between
        horizontal rules), Claude treats it as a document to read and acknowledge.
        It responds: "Now I have all the info I need. Let me create the PptxGenJS
        script..." -- a planning response that never invokes code_execution.

        Placing it in system instructions makes Claude treat it as background context.
        Combined with an explicit "execute immediately" directive, Claude skips the
        planning step and directly invokes code_execution.

    Args:
        template_path: Path to the source .pptx template.
        user_prompt: Content description for the presentation.
        output_path: Desired path for the downloaded PPTX.
        debug: If True, enable verbose response inspection logging.
    """
    if not template_path.exists():
        print(f"Template not found: {template_path}")
        sys.exit(1)

    # Step 1: Extract template styling as markdown
    print("Extracting template styling as markdown...")
    template_markdown = extract_template_to_markdown(template_path)
    print(f"Styling guide extracted ({len(template_markdown)} characters)")

    if debug:
        logger.debug("Template markdown preview (first 500 chars):\n%s", template_markdown[:500])

    # Step 2: Create agent -- styling guide goes into system instructions.
    #
    # CRITICAL FIX: Previously the styling guide was injected into the user message
    # via build_styled_prompt(). This caused Claude to read the large markdown block,
    # acknowledge it conversationally ("Now I have all the info I need..."), and return
    # a text-only planning response without ever invoking code_execution.
    #
    # Solution: move the styling guide to system instructions (instructions list).
    # Claude treats system instructions as background knowledge rather than a document
    # requiring acknowledgment. Adding an explicit "execute immediately" directive
    # ensures Claude acts rather than plans.
    #
    # NOTE: Do NOT pass betas=["context-1m-2025-08-07"] here. That beta is unnecessary
    # (the template markdown is ~6000 chars, not 1M tokens) and is incompatible with
    # the skills container API. When combined with the required skills betas, it
    # prevents the code_execution tool from being engaged, causing Claude to return
    # a text-only planning response instead of invoking code_execution.
    agent = Agent(
        name="Styled Presentation Creator",
        model=Claude(
            id="claude-sonnet-4-5-20250929",
            skills=[
                {"type": "anthropic", "skill_id": "pptx", "version": "latest"},
            ],
        ),
        instructions=[
            "You are a presentation specialist with PowerPoint creation skills.",
            # Force immediate execution -- this is critical.
            # Without this, Claude describes what it will do instead of doing it.
            "IMPORTANT: When asked to create a presentation, IMMEDIATELY invoke "
            "code_execution to generate and save the file. Do NOT describe what you "
            "will do. Do NOT say 'Let me create...' or 'Now I have all the info...'. "
            "Execute the PptxGenJS code right away and return the result.",
            "Apply the template styling guide exactly when generating PPTX files.",
            "Use the specified colors, fonts, and dimensions from the styling guide.",
            "Do not invent colors or fonts -- only use values from the styling guide.",
            # Styling guide injected here: Claude treats instructions as background
            # knowledge, not as a document to acknowledge or summarize.
            "The following is the template styling guide. Apply these specifications "
            "exactly when generating the PPTX:\n\n" + template_markdown,
        ],
        markdown=True,
    )

    # Step 3: Run agent with short, imperative user message.
    # Keep the user message short -- embedding a large document in the user message
    # causes Claude to acknowledge the document rather than act on it.
    print("\nRunning agent with pptx skill and injected styling guide...")
    print("(This may take 30-90 seconds)\n")
    response = agent.run(user_prompt)

    if debug:
        logger.debug("=== Agent raw response ===")
        logger.debug("response.content: %s", response.content)

    print("Agent response:")
    print(response.content)

    # Step 4: Extract generated file IDs
    file_ids = extract_file_ids(response, debug=debug)

    if not file_ids:
        print("\nNo PPTX files were generated by the agent.")
        print("The agent response content was:")
        print("-" * 40)
        print(response.content or "(empty)")
        print("-" * 40)
        if not debug:
            print("\nRun with --debug for detailed response structure inspection.")
        print("Try rephrasing your prompt to explicitly request a PPTX file.")
        sys.exit(0)

    print(f"\nFound {len(file_ids)} generated file(s). Downloading...")

    # Step 5: Download files
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    downloaded = download_skill_files(
        {"file_ids": file_ids},
        client,
        output_dir=str(output_path.parent),
        default_filename=output_path.name,
    )

    if not downloaded:
        print("Download failed -- no files were saved.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Workflow complete!")
    for path in downloaded:
        print(f"  Output: {path}")
    print("=" * 60)
    print("\nApproach used: Template styling injected into system instructions.")
    print("Claude applied the colors, fonts, and dimensions directly in PptxGenJS code.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments and run the markdown-style injection workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate a styled PPTX by injecting template styling as markdown "
            "into Claude's system instructions"
        )
    )
    parser.add_argument(
        "--template",
        "-t",
        default="cookbook/90_models/anthropic/skills/powerpoint_workflow_demo/my_template.pptx",
        help="Path to the source .pptx template file",
    )
    parser.add_argument(
        "--prompt",
        "-p",
        default=(
            "Create a 5-slide company Q4 business review presentation covering: "
            "title slide, key metrics (revenue, customers, growth), "
            "major achievements, challenges and lessons learned, "
            "and Q1 goals. Save it as 'styled_q4_review.pptx'."
        ),
        help="Content description for the presentation",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="cookbook/90_models/anthropic/skills/powerpoint_workflow_demo/styled_q4_review.pptx",
        help="Output path for the generated PPTX",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Enable verbose debug logging: logs response type, attributes, "
            "message count, provider_data, extra_data, and file ID extraction"
        ),
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
        logger.debug("Debug logging enabled")
    else:
        logging.basicConfig(level=logging.WARNING)

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    print("=" * 60)
    print("PPTX Agent with Markdown-Injected Template Styling")
    print("=" * 60)

    run_workflow(
        template_path=Path(args.template),
        user_prompt=args.prompt,
        output_path=Path(args.output),
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
