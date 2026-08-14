import json
import warnings
from textwrap import dedent
from typing import Callable, List, Optional

from agno.tools import Toolkit


class UserControlFlowTools(Toolkit):
    def __init__(
        self,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        get_user_input: bool = True,
        **kwargs,
    ):
        """Toolkit that allows the agent to interrupt execution and request user input.

        Args:
            instructions: Custom instructions for the toolkit. Defaults to built-in guidelines.
            add_instructions: Whether to add instructions to the agent's system prompt.
            get_user_input: Whether to enable the get_user_input tool.
            **kwargs: Additional arguments passed to the Toolkit base class.
        """
        # Backwards compat for old param names
        if "enable_get_user_input" in kwargs:
            warnings.warn("enable_get_user_input is deprecated, use get_user_input", DeprecationWarning, stacklevel=2)
            get_user_input = kwargs.pop("enable_get_user_input")

        if instructions is None:
            self.instructions = self.DEFAULT_INSTRUCTIONS
        else:
            self.instructions = instructions

        tools: List[Callable] = []
        if get_user_input:
            tools.append(self.get_user_input)

        super().__init__(
            name="user_control_flow_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=tools,
            stop_after_tool_call_tools=["get_user_input"],
            **kwargs,
        )

    def get_user_input(self, user_input_fields: list[dict]) -> str:
        """Use this tool to get user input for the given fields. Provide all the fields that you require the user to fill in, as if they were filling in a form.

        Args:
            user_input_fields (list[dict[str, str]]): A list of dictionaries, each containing the following keys:
                - field_name: The name of the field to get input for.
                - field_type: The type of the field to get input for. Only valid python types are supported (e.g. str, int, float, bool, list, dict, etc.).
                - field_description: A description of the field to get input for.

        Returns:
            str: JSON string confirming user input was received.
        """
        # Agent logic will interrupt the run and wait for user input
        return json.dumps({"status": "success", "message": "User input received"})

    # --------------------------------------------------------------------------------
    # Default instructions
    # --------------------------------------------------------------------------------

    DEFAULT_INSTRUCTIONS = dedent(
        """\
        You have access to the `get_user_input` tool to get user input for the given fields.

        1. **Get User Input**:
            - Purpose: When you have call a tool/function where you don't have enough information, don't say you can't do it, just use the `get_user_input` tool to get the information you need from the user.
            - Usage: Call `get_user_input` with the fields you require the user to fill in for you to continue your task.

        ## IMPORTANT GUIDELINES
        - **Don't respond and ask the user for information.** Just use the `get_user_input` tool to get the information you need from the user.
        - **Don't make up information you don't have.** If you don't have the information, use the `get_user_input` tool to get the information you need from the user.
        - **Include only the required fields.** Include only the required fields in the `user_input_fields` parameter of the `get_user_input` tool. Don't include fields you already have the information for.
        - **Provide a clear and concise description of the field.** Clearly describe the field in the `field_description` parameter of the `user_input_fields` parameter of the `get_user_input` tool.
        - **Provide a type for the field.** Fill the `field_type` parameter of the `user_input_fields` parameter of the `get_user_input` tool with the type of the field.

        ## INPUT VALIDATION AND CONVERSION
        - **Boolean fields**: Only explicit positive responses are considered True:
          * True values: 'true', 'yes', 'y', '1', 'on', 't', 'True', 'YES', 'Y', 'T'
          * False values: Everything else including 'false', 'no', 'n', '0', 'off', 'f', empty strings, unanswered fields, or any other input
          * **CRITICAL**: Empty/unanswered fields should be treated as False (not selected)
        - **Users can leave fields unanswered.** Empty responses are valid and should be treated as False for boolean fields.
        - **NEVER ask for the same field twice.** Once you receive ANY user input for a field (including empty strings), accept it and move on.
        - **DO NOT validate or re-request input.** Accept whatever the user provides and convert it appropriately.
        - **Proceed with only the fields that were explicitly answered as True.** Skip or ignore fields that are False/unanswered.
        - **Complete the task immediately after receiving all user inputs, do not ask for confirmation or re-validation.**
        """
    )
