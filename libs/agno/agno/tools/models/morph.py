import os
from os import getenv
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


class MorphTools(Toolkit):
    """Tools for interacting with Morph's Fast Apply API for code editing"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.morphllm.com/v1",
        model: str = "morph-v3-large",
        **kwargs,
    ):
        """Initialize Morph Fast Apply tools.

        Args:
            api_key: Morph API key. If not provided, will look for MORPH_API_KEY environment variable.
            base_url: The base URL for the Morph API.
            model: The Morph model to use. Options:
                  - "morph-v3-fast" (4500+ tok/sec, 96% accuracy)
                  - "morph-v3-large" (2500+ tok/sec, 98% accuracy)
                  - "auto" (automatic selection)
            **kwargs: Additional arguments to pass to Toolkit.
        """
        super().__init__(name="morph_tools", tools=[self.edit_file], **kwargs)

        self.api_key = api_key or getenv("MORPH_API_KEY")
        if not self.api_key:
            raise ValueError("MORPH_API_KEY not set. Please set the MORPH_API_KEY environment variable.")

        self.base_url = base_url
        self.model = model
        self._morph_client: Optional[OpenAI] = None

    def _get_client(self):
        """Get or create the Morph OpenAI client."""
        if self._morph_client is None:
            self._morph_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._morph_client

    def edit_file(
        self,
        target_file: str,
        instructions: str,
        code_edit: str,
        original_code: Optional[str] = None,
    ) -> str:
        """
        Apply code edits to a target file using Morph's Fast Apply API.
    
        This method reads the specified file, sends its content along with
        editing instructions and code edits to Morph's API, and writes the
        resulting code back to the file. A backup of the original file is 
        created before writing changes.
    
        Args:
            target_file (str): Path to the file to be edited.
            instructions (str): High-level instructions describing the intended change.
            code_edit (str): Specific code edit or change to apply.
            original_code (Optional[str], optional): Original content of the file. 
                If not provided, the function reads from target_file.
    
        Returns:
            str: Result message indicating success or failure, and details about 
                the backup and any errors encountered.
        """
        try:
            # Always read the actual file content for backup purposes
            actual_file_content = None
            if os.path.exists(target_file):
                try:
                    with open(target_file, "r", encoding="utf-8") as f:
                        actual_file_content = f.read()
                except Exception as e:
                    return f"Error reading {target_file} for backup: {e}"
            else:
                return f"Error: File {target_file} does not exist."

            # Use provided original_code or fall back to file content
            code_to_process = original_code if original_code is not None else actual_file_content

            # Format the message for Morph's Fast Apply API
            content = f"<instruction>{instructions}</instruction>\n<code>{code_to_process}</code>\n<update>{code_edit}</update>"

            log_debug(f"Input to Morph: {content}")

            client = self._get_client()

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
            )

            if response.choices and response.choices[0].message.content:
                final_code = response.choices[0].message.content

                try:
                    backup_file = f"{target_file}.backup"
                    with open(backup_file, "w", encoding="utf-8") as f:
                        f.write(actual_file_content)

                    # Write the new code
                    with open(target_file, "w", encoding="utf-8") as f:
                        f.write(final_code)
                    return f"Successfully applied edit to {target_file} using Morph Fast Apply and wrote back to file:\n\n```{final_code}\n```\n\n✅ File updated! Original content backed up as {backup_file}"

                except Exception as e:
                    return f"Successfully applied edit but failed to write back to {target_file}: {e}\n\nFinal code:\n```\n{final_code}\n```"

            else:
                return f"Failed to apply edit to {target_file}: No response from Morph API"

        except Exception as e:
            log_error(f"Failed to apply edit using Morph Fast Apply: {e}")
            return f"Failed to apply edit to {target_file}: {e}"
