from datetime import datetime
from typing import Dict, List, Optional

from agno.agent.agent import Agent
from agno.models.google import Gemini
from agno.run.response import RunResponse
from agno.tools.redmine import RedmineTools
from agno.utils.log import logger
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field


class Task(BaseModel):
    task_number: str = Field(None, description="The task number")
    task_title: str = Field(..., description="The title of the task")
    task_description: Optional[str] = Field(
        None, description="The description of the task"
    )
    task_assignee: Optional[str] = Field(None, description="The assignee of the task")


class TaskList(BaseModel):
    tasks: List[Task] = Field(..., description="A list of tasks")


class ScrumMasterWorkflow(Workflow):
    description: str = "Generate Redmine tasks or add comments to existing tasks from meeting notes."

    task_agent: Agent = Agent(
        name="Task Agent",
        model=Gemini("gemini-2.0-flash-exp"),
        instructions=[
            "Given a meeting note, generate a list of tasks with titles, descriptions and assignees."
        ],
        response_model=TaskList,
    )

    def get_tasks_from_meeting_notes(self, meeting_notes: str) -> Optional[TaskList]:
        num_tries = 0
        tasks: Optional[TaskList] = None
        while tasks is None and num_tries < 3:
            num_tries += 1
            try:
                response: RunResponse = self.task_agent.run(meeting_notes)
                if (
                    response
                    and response.content
                    and isinstance(response.content, TaskList)
                ):
                    tasks = response.content
                else:
                    logger.warning("Invalid response from task agent, trying again...")
            except Exception as e:
                logger.warning(f"Error generating tasks: {e}")

        return tasks

    def run(
        self, meeting_notes: str,  redmine_users: Dict[str, int],
    ) -> RunResponse:
        logger.info(f"Generating tasks from meeting notes: {meeting_notes}")
        current_date = datetime.now().strftime("%Y-%m-%d")

        taskList = self.get_tasks_from_meeting_notes(meeting_notes)
        redmine_tools = RedmineTools()
        for task in taskList.tasks:
            if task.task_number:
                redmine_tools.add_comment(task.task_number, task.task_description)
            else:
                redmine_tools.create_issue('primeiro-teste', task.task_title, task.task_description, redmine_users[task.task_assignee])

        return RunResponse()


# Create the workflow
scrum_master = ScrumMasterWorkflow(
    session_id="scrum-master",
)

# meeting_notes = open("planning_meeting_notes.txt", "r").read()
meeting_notes = open("daily_meeting_notes.txt", "r").read()

users_id = {
    "Laura Melo": 7,
    "Wagner Silva": 8,
    "Rodrigo Menescal": 9,
    "Gean Correia": 10,
    "Deise Lobo": 11,
}

# Run workflow
scrum_master.run(meeting_notes=meeting_notes, redmine_users=users_id)
