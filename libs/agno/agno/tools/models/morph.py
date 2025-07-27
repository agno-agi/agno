import os
from os import getenv
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

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
        Use this tool to make an edit to an existing file using Morph's Fast Apply API.

        This will be read by Morph's specialized model, which will quickly apply the edit with 98% accuracy.
        You should make it clear what the edit is, while also minimizing the unchanged code you write.
        When writing the edit, you should specify each edit in sequence, with the special comment 
        // ... existing code ... to represent unchanged code in between edited lines.

        For example:

        // ... existing code ...
        FIRST_EDIT
        // ... existing code ...
        SECOND_EDIT
        // ... existing code ...
        THIRD_EDIT
        // ... existing code ...

        You should still bias towards repeating as few lines of the original file as possible to convey the change.
        But, each edit should contain sufficient context of unchanged lines around the code you're editing to resolve ambiguity.
        DO NOT omit spans of pre-existing code (or comments) without using the // ... existing code ... comment to indicate its absence.

        Args:
            target_file: The target file to modify
            instructions: A single sentence instruction describing what you are going to do for the sketched edit. 
                         Use the first person to describe what you are going to do. 
                         Example: "I am adding error handling to the user authentication function"
            code_edit: Specify ONLY the precise lines of code that you wish to edit. 
                      Use // ... existing code ... to represent unchanged code.
            original_code: The complete original code. If not provided, will read from target_file.

        Returns:
            A message indicating success and the final merged code.
        """
        try:
            # Read original code if not provided
            if not original_code:
                if not os.path.exists(target_file):
                    return f"Error: File {target_file} does not exist."
                
                try:
                    with open(target_file, 'r', encoding='utf-8') as f:
                        original_code = f.read()
                except Exception as e:
                    return f"Error reading {target_file}: {e}"

            # Format the message for Morph's Fast Apply API
            content = f"<instruction>{instructions}</instruction>\n<code>{original_code}</code>\n<update>{code_edit}</update>"

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
                    # Create backup first
                    backup_file = f"{target_file}.backup"
                    with open(backup_file, 'w', encoding='utf-8') as f:
                        f.write(original_code)
                        
                    # Write the new code
                    with open(target_file, 'w', encoding='utf-8') as f:
                        f.write(final_code)
                    return f"Successfully applied edit to {target_file} using Morph Fast Apply and wrote back to file:\n\n```{final_code}\n```\n\n✅ File updated! Backup saved as {backup_file}"
                    
                except Exception as e:
                    return f"Successfully applied edit but failed to write back to {target_file}: {e}\n\nFinal code:\n```\n{final_code}\n```"
                
            else:
                return f"Failed to apply edit to {target_file}: No response from Morph API"

        except Exception as e:
            log_error(f"Failed to apply edit using Morph Fast Apply: {e}")
            return f"Failed to apply edit to {target_file}: {e}"