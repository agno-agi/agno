import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from agno.tools.toolkit import Toolkit
from agno.utils.log import logger


class MermaidTools(Toolkit):
    def __init__(self):
        """
        Initialize the MermaidTools with predefined diagram types and validation.
        """
        super().__init__("mermaid_tool")

        # Register the tool functions
        self.register(self.generate_mermaid)
        self.register(self.render_mermaid)

        # Define supported diagram types
        self.supported_types = {
            "flowchart": ["LR", "TD", "BT", "RL"],
            "sequenceDiagram": [],
            "classDiagram": [],
            "stateDiagram": [],
            "erDiagram": [],
            "gantt": [],
            "pie": [],
        }

    def validate_diagram_type(self, diagram_type: str) -> tuple[bool, str]:
        """
        Validate the diagram type and direction.

        Args:
            diagram_type (str): The type of diagram to validate

        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        parts = diagram_type.strip().split()
        base_type = parts[0] if parts else ""

        if base_type not in self.supported_types:
            return False, f"Unsupported diagram type: {base_type}. Supported types: {list(self.supported_types.keys())}"

        if len(parts) > 1 and base_type == "flowchart":
            direction = parts[1]
            if direction not in self.supported_types["flowchart"]:
                return (
                    False,
                    f"Invalid flowchart direction: {direction}. Supported directions: {self.supported_types['flowchart']}",
                )

        return True, ""

    def generate_mermaid(self, diagram_type: str, content: str) -> str:
        """
        Generate a Mermaid diagram definition with validation and proper formatting.

        Args:
            diagram_type (str): The type of Mermaid diagram (e.g., "flowchart LR", "sequenceDiagram")
            content (str): The actual content of the diagram

        Returns:
            str: JSON response with the Mermaid diagram definition or error message
        """
        try:
            logger.debug(f"Generating Mermaid diagram of type: {diagram_type}")

            # Input validation
            if not diagram_type or not content:
                return json.dumps({"error": "Diagram type and content are required", "status": "error"})

            # Validate diagram type
            is_valid, error_message = self.validate_diagram_type(diagram_type)
            if not is_valid:
                return json.dumps({"error": error_message, "status": "error"})

            # Clean and format the content
            cleaned_content = self._clean_content(content)

            # Construct the Mermaid code
            mermaid_code = f"{diagram_type}\n{cleaned_content}"

            return json.dumps(
                {"message": "Mermaid diagram generated successfully", "status": "success", "diagram": mermaid_code},
                indent=2,
            )

        except Exception as e:
            logger.error(f"Error generating Mermaid diagram: {str(e)}")
            return json.dumps({"error": f"Failed to generate diagram: {str(e)}", "status": "error"})

    def render_mermaid(self, mermaid_code: str) -> str:
        """
        Render a Mermaid diagram with proper markdown formatting and error handling.

        Args:
            mermaid_code (str): The Mermaid diagram definition

        Returns:
            str: JSON response with the formatted markdown or error message
        """
        try:
            logger.debug("Rendering Mermaid diagram")

            if not mermaid_code:
                return json.dumps({"error": "Mermaid code is required", "status": "error"})

            # Clean the mermaid code
            cleaned_code = self._clean_content(mermaid_code)

            # Format for markdown
            mermaid_md = f"\n{cleaned_code}\n"

            return json.dumps(
                {"message": "Diagram rendered successfully", "status": "success", "markdown": mermaid_md}, indent=2
            )

        except Exception as e:
            logger.error(f"Error rendering Mermaid diagram: {str(e)}")
            return json.dumps({"error": f"Failed to render diagram: {str(e)}", "status": "error"})

    def _clean_content(self, content: str) -> str:
        """
        Clean and format diagram content.

        Args:
            content (str): Raw diagram content

        Returns:
            str: Cleaned and properly formatted content
        """
        # Remove extra whitespace and empty lines
        lines = [line.strip() for line in content.split("\n") if line.strip()]

        # Ensure proper indentation
        return "\n    ".join(lines)
