import json
from textwrap import dedent
from typing import Any, List, Optional
from uuid import uuid4

from agno.db.base import BaseDb
from agno.db.schemas import UserMemory
from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class MemoryTools(Toolkit):
    def __init__(
        self,
        db: BaseDb,
        enable_get_memories: bool = True,
        enable_add_memory: bool = True,
        enable_update_memory: bool = True,
        enable_delete_memory: bool = True,
        enable_analyze: bool = True,
        enable_think: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        add_few_shot: bool = True,
        few_shot_examples: Optional[str] = None,
        all: bool = False,
        **kwargs,
    ):
        # Add instructions for using this toolkit
        if instructions is None:
            self.instructions = self.DEFAULT_INSTRUCTIONS
            if add_few_shot:
                if few_shot_examples is not None:
                    self.instructions += "\n" + few_shot_examples
                else:
                    self.instructions += "\n" + self.FEW_SHOT_EXAMPLES
        else:
            self.instructions = instructions

        # The database to use for memory operations
        self.db: BaseDb = db

        tools: List[Any] = []
        if enable_think or all:
            tools.append(self.think)
        if enable_get_memories or all:
            tools.append(self.get_memories)
        if enable_add_memory or all:
            tools.append(self.add_memory)
        if enable_update_memory or all:
            tools.append(self.update_memory)
        if enable_delete_memory or all:
            tools.append(self.delete_memory)
        if enable_analyze or all:
            tools.append(self.analyze)

        super().__init__(
            name="memory_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=tools,
            **kwargs,
        )

    def think(self, run_context: RunContext, thought: str) -> str:
        """Use this tool as a scratchpad to reason about memory operations, refine your approach, brainstorm memory content, or revise your plan.

        Call `Think` whenever you need to figure out what to do next, analyze the user's requirements, plan memory operations, or decide on execution strategy.
        You should use this tool as frequently as needed.

        Args:
            thought: Your thought process and reasoning about memory operations.
        """
        try:
            log_debug(f"Memory Thought: {thought}")

            # Add the thought to the session state
            if run_context.session_state is None:
                run_context.session_state = {}
            if "memory_thoughts" not in run_context.session_state:
                run_context.session_state["memory_thoughts"] = []
            run_context.session_state["memory_thoughts"].append(thought)

            # Return the full log of thoughts and the new thought
            thoughts = "\n".join([f"- {t}" for t in run_context.session_state["memory_thoughts"]])
            formatted_thoughts = dedent(
                f"""Memory Thoughts:
                {thoughts}
                """
            ).strip()
            return formatted_thoughts
        except Exception as e:
            log_error(f"Error recording memory thought: {e}")
            return f"Error recording memory thought: {e}"

    def get_memories(self, run_context: RunContext) -> str:
        """
        Use this tool to get a list of memories for the current user from the database.
        """
        try:
            # Get user info from run context
            user_id = run_context.user_id

            memories = self.db.get_user_memories(user_id=user_id)

            # Store the result in session state for analysis
            if run_context.session_state is None:
                run_context.session_state = {}
            if "memory_operations" not in run_context.session_state:
                run_context.session_state["memory_operations"] = []

            operation_result = {
                "operation": "get_memories",
                "success": True,
                "memories": [memory.to_dict() for memory in memories],  # type: ignore
                "error": None,
            }
            run_context.session_state["memory_operations"].append(operation_result)

            return json.dumps([memory.to_dict() for memory in memories], indent=2)  # type: ignore
        except Exception as e:
            log_error(f"Error getting memories: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    def add_memory(
        self,
        run_context: RunContext,
        memory: str,
        topics: Optional[List[str]] = None,
    ) -> str:
        """Use this tool to add a new memory to the database.

        Args:
            memory: The memory content to store
            topics: Optional list of topics associated with this memory

        Returns:
            str: JSON string containing the created memory information
        """
        try:
            log_debug(f"Adding memory: {memory}")

            # Get user info from run context
            user_id = run_context.user_id

            # Create UserMemory object
            user_memory = UserMemory(
                memory_id=str(uuid4()),
                memory=memory,
                topics=topics,
                user_id=user_id,
            )

            # Add to database
            created_memory = self.db.upsert_user_memory(user_memory)

            # Store the result in session state for analysis
            if run_context.session_state is None:
                run_context.session_state = {}
            if "memory_operations" not in run_context.session_state:
                run_context.session_state["memory_operations"] = []

            memory_dict = created_memory.to_dict() if created_memory else None  # type: ignore

            operation_result = {
                "operation": "add_memory",
                "success": created_memory is not None,
                "memory": memory_dict,
                "error": None,
            }
            run_context.session_state["memory_operations"].append(operation_result)

            if created_memory:
                return json.dumps({"success": True, "operation": "add_memory", "memory": memory_dict}, indent=2)
            else:
                return json.dumps(
                    {"success": False, "operation": "add_memory", "error": "Failed to create memory"}, indent=2
                )

        except Exception as e:
            log_error(f"Error adding memory: {e}")
            return json.dumps({"success": False, "operation": "add_memory", "error": str(e)}, indent=2)

    def update_memory(
        self,
        run_context: RunContext,
        memory_id: str,
        memory: Optional[str] = None,
        topics: Optional[List[str]] = None,
    ) -> str:
        """Use this tool to update an existing memory in the database.

        Args:
            memory_id: The ID of the memory to update
            memory: Updated memory content (if provided)
            topics: Updated list of topics (if provided)

        Returns:
            str: JSON string containing the updated memory information
        """
        try:
            log_debug(f"Updating memory: {memory_id}")

            # First get the existing memory
            existing_memory = self.db.get_user_memory(memory_id)
            if not existing_memory:
                return json.dumps(
                    {"success": False, "operation": "update_memory", "error": f"Memory with ID {memory_id} not found"},
                    indent=2,
                )

            # Update fields if provided
            updated_memory = UserMemory(
                memory=memory if memory is not None else existing_memory.memory,  # type: ignore
                memory_id=memory_id,
                topics=topics if topics is not None else existing_memory.topics,  # type: ignore
                user_id=existing_memory.user_id,  # type: ignore
            )

            # Update in database
            updated_result = self.db.upsert_user_memory(updated_memory)

            # Store the result in session state for analysis
            if run_context.session_state is None:
                run_context.session_state = {}
            if "memory_operations" not in run_context.session_state:
                run_context.session_state["memory_operations"] = []

            memory_dict = updated_result.to_dict() if updated_result else None  # type: ignore

            operation_result = {
                "operation": "update_memory",
                "success": updated_result is not None,
                "memory": memory_dict,
                "error": None,
            }
            run_context.session_state["memory_operations"].append(operation_result)

            if updated_result:
                return json.dumps({"success": True, "operation": "update_memory", "memory": memory_dict}, indent=2)
            else:
                return json.dumps(
                    {"success": False, "operation": "update_memory", "error": "Failed to update memory"}, indent=2
                )

        except Exception as e:
            log_error(f"Error updating memory: {e}")
            return json.dumps({"success": False, "operation": "update_memory", "error": str(e)}, indent=2)

    def delete_memory(
        self,
        run_context: RunContext,
        memory_id: str,
    ) -> str:
        """Use this tool to delete a memory from the database.

        Args:
            memory_id: The ID of the memory to delete

        Returns:
            str: JSON string containing the deletion result
        """
        try:
            log_debug(f"Deleting memory: {memory_id}")

            # Check if memory exists before deletion
            existing_memory = self.db.get_user_memory(memory_id)
            if not existing_memory:
                return json.dumps(
                    {"success": False, "operation": "delete_memory", "error": f"Memory with ID {memory_id} not found"},
                    indent=2,
                )

            # Delete from database
            self.db.delete_user_memory(memory_id)

            # Store the result in session state for analysis
            if run_context.session_state is None:
                run_context.session_state = {}
            if "memory_operations" not in run_context.session_state:
                run_context.session_state["memory_operations"] = []

            memory_dict = existing_memory.to_dict() if existing_memory else None  # type: ignore

            operation_result = {
                "operation": "delete_memory",
                "success": True,
                "memory_id": memory_id,
                "deleted_memory": memory_dict,
                "error": None,
            }
            run_context.session_state["memory_operations"].append(operation_result)

            return json.dumps(
                {
                    "success": True,
                    "operation": "delete_memory",
                    "memory_id": memory_id,
                    "deleted_memory": memory_dict,
                },
                indent=2,
            )

        except Exception as e:
            log_error(f"Error deleting memory: {e}")
            return json.dumps({"success": False, "operation": "delete_memory", "error": str(e)}, indent=2)

    def analyze(self, run_context: RunContext, analysis: str) -> str:
        """Use this tool to evaluate whether the memory operations results are correct and sufficient.
        If not, go back to "Think" or use memory operations with refined parameters.

        Args:
            analysis: Your analysis of the memory operations results.
        """
        try:
            log_debug(f"Memory Analysis: {analysis}")

            # Add the analysis to the session state
            if run_context.session_state is None:
                run_context.session_state = {}
            if "memory_analysis" not in run_context.session_state:
                run_context.session_state["memory_analysis"] = []
            run_context.session_state["memory_analysis"].append(analysis)

            # Return the full log of analysis and the new analysis
            analysis_log = "\n".join([f"- {a}" for a in run_context.session_state["memory_analysis"]])
            formatted_analysis = dedent(
                f"""Memory Analysis:
                {analysis_log}
                """
            ).strip()
            return formatted_analysis
        except Exception as e:
            log_error(f"Error recording memory analysis: {e}")
            return f"Error recording memory analysis: {e}"

    DEFAULT_INSTRUCTIONS = dedent("""\
        You have access to the Think, Add Memory, Update Memory, Delete Memory, and Analyze tools that will help you manage user memories and analyze their operations. Use these tools as frequently as needed to successfully complete memory management tasks.

        ## How to use the Think, Memory Operations, and Analyze tools:

        1. **Think**
        - Purpose: A scratchpad for planning memory operations, brainstorming memory content, and refining your approach. You never reveal your "Think" content to the user.
        - Usage: Call `think` whenever you need to figure out what memory operations to perform, analyze requirements, or decide on strategy.

        2. **Get Memories**
        - Purpose: Retrieves a list of memories from the database for the current user.
        - Usage: Call `get_memories` when you need to retrieve memories for the current user.

        3. **Add Memory**
        - Purpose: Creates new memories in the database with specified content and metadata.
        - Usage: Call `add_memory` with memory content and optional topics when you need to store new information.

        4. **Update Memory**
        - Purpose: Modifies existing memories in the database by memory ID.
        - Usage: Call `update_memory` with a memory ID and the fields you want to change. Only specify the fields that need updating.

        5. **Delete Memory**
        - Purpose: Removes memories from the database by memory ID.
        - Usage: Call `delete_memory` with a memory ID when a memory is no longer needed or requested to be removed.

        6. **Analyze**
        - Purpose: Evaluate whether the memory operations results are correct and sufficient. If not, go back to "Think" or use memory operations with refined parameters.
        - Usage: Call `analyze` after performing memory operations to verify:
            - Success: Did the operation complete successfully?
            - Accuracy: Is the memory content correct and well-formed?
            - Completeness: Are all required fields populated appropriately?
            - Errors: Were there any failures or unexpected behaviors?

        **Important Guidelines**:
        - Do not include your internal chain-of-thought in direct user responses.
        - Use "Think" to reason internally. These notes are never exposed to the user.
        - When you provide a final answer to the user, be clear, concise, and based on the memory operation results.
        - If memory operations fail or produce unexpected results, acknowledge limitations and explain what went wrong.
        - Always verify memory IDs exist before attempting updates or deletions.
        - Use descriptive topics and clear memory content to make memories easily searchable and understandable.\
    """)

    FEW_SHOT_EXAMPLES = dedent("""\
        You can refer to the examples below as guidance for how to use each tool.

        ### Examples

        #### Example 1: Adding User Preferences

        User: I prefer vegetarian recipes and I'm allergic to nuts.
        Think: I should store the user's dietary preferences. I should create a memory with this information and use relevant topics for easy retrieval.
        Add Memory: memory="User prefers vegetarian recipes and is allergic to nuts", topics=["dietary_preferences", "allergies", "food"]
        Analyze: Successfully created memory with dietary preferences. The topics are well-chosen for future retrieval. This should help with future food-related requests.

        Final Answer: Noted. I've stored your dietary preferences. I'll remember that you prefer vegetarian recipes and have a nut allergy for future reference.

        #### Example 2: Updating Existing Information

        User: Actually, update my dietary info - I'm now eating fish too, so I'm pescatarian.
        Think: The user wants to update their previous dietary preference from vegetarian to pescatarian. I need to find their existing dietary memory and update it.
        Update Memory: memory_id="previous_memory_id", memory="User follows pescatarian diet (vegetarian + fish) and is allergic to nuts", topics=["dietary_preferences", "allergies", "food", "pescatarian"]
        Analyze: Successfully updated the dietary preference memory. The content now accurately reflects pescatarian diet and maintains the nut allergy information.

        Final Answer: I've updated your dietary preferences to reflect that you follow a pescatarian diet (vegetarian plus fish) while maintaining your nut allergy information.

        #### Example 3: Removing Outdated Information

        User: Please forget about my old work schedule - it's completely changed.
        Think: The user wants me to delete their old work schedule memory since it's no longer relevant. I should find and remove that memory.
        Delete Memory: memory_id="work_schedule_memory_id"
        Analyze: Successfully deleted the outdated work schedule memory. The old information won't interfere with future scheduling requests.

        Final Answer: I've removed your old work schedule information. Feel free to share your new schedule when you're ready, and I'll store the updated information.

        #### Example 4: Retrieving Memories

        User: What have you remembered about me?
        Think: The user wants to retrieve memories about themselves. I should use the get_memories tool to retrieve the memories.
        Get Memories:
        Analyze: Successfully retrieved the memories about the user. The memories are relevant to the user's preferences and activities.

        Final Answer: I've retrieved the memories about you. You like to hike in the mountains on weekends and travel to new places and experience different cultures. You are planning to travel to Africa in December.\
    """)
