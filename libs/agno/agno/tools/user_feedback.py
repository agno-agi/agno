from textwrap import dedent
from typing import List, Optional

from pydantic import BaseModel, Field

from agno.tools import Toolkit


class AskUserOption(BaseModel):
    """An option the user can select."""

    label: str = Field(..., description="Short display text for this option (1-5 words).")
    description: Optional[str] = Field(None, description="Explanation of what this option means.")


class AskUserQuestion(BaseModel):
    """A structured question with predefined options."""

    question: str = Field(..., description="The question to ask the user. Must end with a question mark.")
    header: str = Field(..., description="Short label for the question (max 12 chars), e.g. 'Destination'.")
    options: List[AskUserOption] = Field(..., description="2-4 options for the user to choose from.")
    multi_select: bool = Field(False, description="If true, the user can select multiple options.")


class UserFeedbackTools(Toolkit):
    def __init__(
        self,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        """A toolkit that lets an agent present structured questions with predefined options to the user."""

        if instructions is None:
            self.instructions = self.DEFAULT_INSTRUCTIONS
        else:
            self.instructions = instructions

        super().__init__(
            name="user_feedback_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=[self.ask_user],
            **kwargs,
        )

    def ask_user(self, questions: List[AskUserQuestion]) -> str:
        """Present structured questions with predefined options to the user.

        Args:
            questions: A list of questions to present to the user, each with a header, question text, and options.
        """
        # The agent logic intercepts this call and pauses for user feedback
        return "User feedback received"

    # --------------------------------------------------------------------------------
    # Default instructions
    # --------------------------------------------------------------------------------

    DEFAULT_INSTRUCTIONS = dedent(
        """\
        You have access to the `ask_user` tool to present structured questions with predefined options.

        ## Usage
        - Use `ask_user` when you need the user to choose between specific options.
        - Each question should have a short `header`, a clear `question` text, and a list of `options`.
        - Each option needs a `label` and an optional `description`.
        - Set `multi_select` to true if the user can select more than one option.

        ## Guidelines
        - Provide 2-4 options per question.
        - Keep headers short (max 12 characters).
        - Write clear, specific questions that end with a question mark.
        - Use `multi_select: true` only when choices are not mutually exclusive.
        """
    )
