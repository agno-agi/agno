"""Task management tools for autonomous team execution (mode=tasks)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.team import Team

from copy import deepcopy
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Union,
)

from agno.agent import Agent
from agno.exceptions import RunCancelledException
from agno.media import Audio, File, Image, Video
from agno.run import RunContext
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.base import RunStatus
from agno.run.team import (
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.session import TeamSession
from agno.team.task import TaskList, TaskStatus, save_task_list
from agno.tools.function import Function
from agno.utils.log import (
    log_debug,
    use_agent_logger,
    use_team_logger,
)
from agno.utils.merge_dict import merge_dictionaries, merge_parallel_session_states
from agno.utils.response import check_if_run_cancelled
from agno.utils.team import (
    add_interaction_to_team_run_context,
    format_member_agent_task,
)


def _get_task_management_tools(
    team: "Team",
    task_list: TaskList,
    run_response: TeamRunOutput,
    run_context: RunContext,
    session: TeamSession,
    team_run_context: Dict[str, Any],
    user_id: Optional[str] = None,
    stream: bool = False,
    stream_events: bool = False,
    async_mode: bool = False,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    audio: Optional[Sequence[Audio]] = None,
    files: Optional[Sequence[File]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
) -> List[Function]:
    """Build task management tools that close over team state.

    Returns a list of Function objects the leader model can call as tools.
    """
    _images: List[Image] = list(images) if images else []
    _videos: List[Video] = list(videos) if videos else []
    _audio: List[Audio] = list(audio) if audio else []
    _files: List[File] = list(files) if files else []

    from agno.team._init import _initialize_member
    from agno.team._run import _update_team_media
    from agno.team._tools import (
        _determine_team_member_interactions,
        _find_member_by_id,
        _get_history_for_member_agent,
        _propagate_member_pause,
    )

    # ------------------------------------------------------------------
    # Tool: create_task
    # ------------------------------------------------------------------
    def create_task(
        title: str,
        description: str = "",
        assignee: str = "",
        depends_on: Optional[List[str]] = None,
    ) -> str:
        """Create a new task for the team to work on.

        Args:
            title (str): A short, actionable title for the task.
            description (str): Detailed description of what needs to be done.
            assignee (str): The member_id to assign this task to. Must be a valid member_id.
            depends_on (list, optional): List of task IDs that must complete before this task can start.
        Returns:
            str: Confirmation with the new task ID.
        """
        task = task_list.create_task(
            title=title,
            description=description,
            assignee=assignee,
            dependencies=depends_on or [],
        )
        save_task_list(run_context.session_state, task_list)
        log_debug(f"Task created: [{task.id}] {task.title}")
        return f"Task created: [{task.id}] {task.title} (status: {task.status.value})"

    # ------------------------------------------------------------------
    # Tool: update_task_status
    # ------------------------------------------------------------------
    def update_task_status(
        task_id: str,
        status: str,
        result: Optional[str] = None,
    ) -> str:
        """Update the status of a task. Use this to mark tasks you handle yourself as completed.

        Args:
            task_id (str): The ID of the task to update.
            status (str): New status. One of: pending, in_progress, completed, failed.
            result (str, optional): The result or outcome of the task (when completing).
        Returns:
            str: Confirmation of the update.
        """
        try:
            new_status = TaskStatus(status)
        except ValueError:
            return f"Invalid status '{status}'. Must be one of: pending, in_progress, completed, failed."
        if new_status == TaskStatus.blocked:
            return "Cannot manually set status to 'blocked'. Blocked status is managed automatically based on task dependencies."

        updates: Dict[str, Any] = {"status": new_status}
        if result is not None:
            updates["result"] = result

        task = task_list.update_task(task_id, **updates)
        if task is None:
            return f"Task with ID '{task_id}' not found."
        save_task_list(run_context.session_state, task_list)
        return f"Task [{task.id}] '{task.title}' updated to {task.status.value}."

    # ------------------------------------------------------------------
    # Tool: list_tasks
    # ------------------------------------------------------------------
    def list_tasks() -> str:
        """List all tasks with their current status, assignees, and dependencies.

        Returns:
            str: Formatted task list.
        """
        return task_list.get_summary_string()

    # ------------------------------------------------------------------
    # Tool: add_task_note
    # ------------------------------------------------------------------
    def add_task_note(task_id: str, note: str) -> str:
        """Add a note to a task for tracking progress or communicating context.

        Args:
            task_id (str): The ID of the task.
            note (str): The note to add.
        Returns:
            str: Confirmation.
        """
        task = task_list.get_task(task_id)
        if task is None:
            return f"Task with ID '{task_id}' not found."
        task.notes.append(note)
        save_task_list(run_context.session_state, task_list)
        return f"Note added to task [{task.id}]."

    # ------------------------------------------------------------------
    # Tool: mark_all_complete
    # ------------------------------------------------------------------
    def mark_all_complete(summary: str) -> str:
        """Signal that the overall goal has been achieved. Call this when all tasks are done.

        Args:
            summary (str): A summary of the work done and the final outcome.
        Returns:
            str: Confirmation.
        """
        task_list.goal_complete = True
        task_list.completion_summary = summary
        save_task_list(run_context.session_state, task_list)
        return f"Goal marked as complete. Summary: {summary}"

    # ------------------------------------------------------------------
    # Shared: member setup and post-processing
    # ------------------------------------------------------------------
    def _setup_member_for_task(member_agent: Union[Agent, "Team"], task_description: str):
        """Initialize member and prepare task input. Returns (member_agent_task, history)."""
        _initialize_member(team, member_agent)
        if not team.send_media_to_model:
            member_agent.send_media_to_model = False

        team_member_interactions_str = _determine_team_member_interactions(
            team, team_run_context, images=_images, videos=_videos, audio=_audio, files=_files
        )
        team_history_str = None
        if team.add_team_history_to_members and session:
            team_history_str = session.get_team_history_context(num_runs=team.num_team_history_runs)

        member_agent_task: Any = task_description
        if team_history_str or team_member_interactions_str:
            member_agent_task = format_member_agent_task(
                task_description=member_agent_task,
                team_member_interactions_str=team_member_interactions_str,
                team_history_str=team_history_str,
            )

        history = None
        if hasattr(member_agent, "add_history_to_context") and member_agent.add_history_to_context:
            history = _get_history_for_member_agent(team, session, member_agent)
            if history and isinstance(member_agent_task, str):
                from agno.models.message import Message

                history.append(Message(role="user", content=member_agent_task))

        return member_agent_task, history

    def _post_process_member_run(
        member_run_response: Optional[Union[TeamRunOutput, RunOutput]],
        member_agent: Union[Agent, "Team"],
        member_agent_task: Any,
        member_session_state_copy: Optional[Dict[str, Any]],
        tool_name: str = "execute_task",
        skip_session_merge: bool = False,
    ) -> None:
        """Post-process a member run: update parent IDs, interactions, session state."""
        if member_run_response is not None:
            member_run_response.parent_run_id = run_response.run_id

        # Update tool child_run_id
        if run_response.tools is not None and member_run_response is not None:
            for tool in run_response.tools:
                if tool.tool_name and tool.tool_name.lower() == tool_name and tool.child_run_id is None:
                    tool.child_run_id = member_run_response.run_id
                    break

        member_name = member_agent.name or (member_agent.id if member_agent.id else "Unknown")
        normalized_task = (
            str(member_agent_task)
            if not hasattr(member_agent_task, "content")
            else str(member_agent_task.content or "")
        )
        add_interaction_to_team_run_context(
            team_run_context=team_run_context,
            member_name=member_name,
            task=normalized_task,
            run_response=member_run_response,
        )

        if run_response and member_run_response:
            run_response.add_member_run(member_run_response)

        if member_run_response:
            if (
                not member_agent.store_media
                or not member_agent.store_tool_messages
                or not member_agent.store_history_messages
            ):
                from agno.agent._run import scrub_run_output_for_storage

                scrub_run_output_for_storage(member_agent, run_response=member_run_response)  # type: ignore[arg-type]
            session.upsert_run(member_run_response)

        if run_context.session_state is not None and member_session_state_copy is not None and not skip_session_merge:
            merge_dictionaries(run_context.session_state, member_session_state_copy)

        if member_run_response is not None:
            _update_team_media(team, member_run_response)

    # ------------------------------------------------------------------
    # Tool: execute_task (sync)
    # ------------------------------------------------------------------
    def execute_task(task_id: str, member_id: str) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Execute a task by delegating it to a team member. The member will receive the task
        description and return a result.

        Args:
            task_id (str): The ID of the task to execute.
            member_id (str): The ID of the member to execute the task.
        Returns:
            str: The result of the task execution.
        """
        task = task_list.get_task(task_id)
        if task is None:
            yield f"Task with ID '{task_id}' not found."
            return

        if task.status not in (TaskStatus.pending, TaskStatus.in_progress):
            yield f"Task [{task_id}] is {task.status.value} and cannot be executed."
            return

        result = _find_member_by_id(team, member_id, run_context=run_context)
        if result is None:
            yield f"Member with ID {member_id} not found. Available members:\n{team.get_members_system_message_content(indent=0, run_context=run_context)}"
            return

        _, member_agent = result

        task.status = TaskStatus.in_progress
        task.assignee = member_id
        save_task_list(run_context.session_state, task_list)

        use_agent_logger()
        member_session_state_copy = deepcopy(run_context.session_state)
        member_run_response: Optional[Union[TeamRunOutput, RunOutput]] = None

        try:
            member_task_description = task.description or task.title
            member_agent_task, history = _setup_member_for_task(member_agent, member_task_description)

            if stream:
                member_stream = member_agent.run(
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    session_id=session.session_id,
                    session_state=member_session_state_copy,
                    images=_images,
                    videos=_videos,
                    audio=_audio,
                    files=_files,
                    stream=True,
                    stream_events=stream_events or team.stream_member_events,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    metadata=run_context.metadata,
                    add_session_state_to_context=add_session_state_to_context,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                    yield_run_output=True,
                )
                for event in member_stream:
                    if isinstance(event, (TeamRunOutput, RunOutput)):
                        member_run_response = event
                        continue
                    check_if_run_cancelled(event)
                    event.parent_run_id = event.parent_run_id or run_response.run_id
                    yield event
            else:
                member_run_response = member_agent.run(
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    session_id=session.session_id,
                    session_state=member_session_state_copy,
                    images=_images,
                    videos=_videos,
                    audio=_audio,
                    files=_files,
                    stream=False,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    metadata=run_context.metadata,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                )
                check_if_run_cancelled(member_run_response)
        except RunCancelledException:
            raise
        except Exception as e:
            task.status = TaskStatus.failed
            task.result = f"Member execution error: {e}"
            save_task_list(run_context.session_state, task_list)
            use_team_logger()
            yield f"Task [{task.id}] failed due to member execution error: {e}"
            return

        # Check HITL pause
        if member_run_response is not None and member_run_response.is_paused:
            _propagate_member_pause(run_response, member_agent, member_run_response)
            task.status = TaskStatus.pending  # Reset to pending so it can be retried after HITL
            save_task_list(run_context.session_state, task_list)
            use_team_logger()
            _post_process_member_run(member_run_response, member_agent, member_agent_task, member_session_state_copy)
            yield f"Member '{member_agent.name}' requires human input before continuing. Task [{task.id}] paused."
            return

        # Process result
        use_team_logger()
        _post_process_member_run(member_run_response, member_agent, member_agent_task, member_session_state_copy)

        if member_run_response is not None and member_run_response.status == RunStatus.error:
            task.status = TaskStatus.failed
            task.result = str(member_run_response.content) if member_run_response.content else "Task failed"
            save_task_list(run_context.session_state, task_list)
            yield f"Task [{task.id}] failed: {task.result}"
        elif member_run_response is not None and member_run_response.content:
            content = str(member_run_response.content)
            task.status = TaskStatus.completed
            task.result = content
            save_task_list(run_context.session_state, task_list)
            yield f"Task [{task.id}] completed. Result: {content}"
        else:
            task.status = TaskStatus.completed
            task.result = "No content returned"
            save_task_list(run_context.session_state, task_list)
            yield f"Task [{task.id}] completed with no content."

    # ------------------------------------------------------------------
    # Tool: execute_task (async)
    # ------------------------------------------------------------------
    async def aexecute_task(
        task_id: str, member_id: str
    ) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Execute a task by delegating it to a team member. The member will receive the task
        description and return a result.

        Args:
            task_id (str): The ID of the task to execute.
            member_id (str): The ID of the member to execute the task.
        Returns:
            str: The result of the task execution.
        """
        task = task_list.get_task(task_id)
        if task is None:
            yield f"Task with ID '{task_id}' not found."
            return

        if task.status not in (TaskStatus.pending, TaskStatus.in_progress):
            yield f"Task [{task_id}] is {task.status.value} and cannot be executed."
            return

        result = _find_member_by_id(team, member_id, run_context=run_context)
        if result is None:
            yield f"Member with ID {member_id} not found. Available members:\n{team.get_members_system_message_content(indent=0, run_context=run_context)}"
            return

        _, member_agent = result

        task.status = TaskStatus.in_progress
        task.assignee = member_id
        save_task_list(run_context.session_state, task_list)

        use_agent_logger()
        member_session_state_copy = deepcopy(run_context.session_state)
        member_run_response: Optional[Union[TeamRunOutput, RunOutput]] = None

        try:
            member_task_description = task.description or task.title
            member_agent_task, history = _setup_member_for_task(member_agent, member_task_description)

            if stream:
                member_stream = member_agent.arun(
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    session_id=session.session_id,
                    session_state=member_session_state_copy,
                    images=_images,
                    videos=_videos,
                    audio=_audio,
                    files=_files,
                    stream=True,
                    stream_events=stream_events or team.stream_member_events,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    metadata=run_context.metadata,
                    add_session_state_to_context=add_session_state_to_context,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                    yield_run_output=True,
                )
                async for event in member_stream:
                    if isinstance(event, (TeamRunOutput, RunOutput)):
                        member_run_response = event
                        continue
                    check_if_run_cancelled(event)
                    event.parent_run_id = event.parent_run_id or run_response.run_id
                    yield event
            else:
                member_run_response = await member_agent.arun(  # type: ignore[misc]
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    session_id=session.session_id,
                    session_state=member_session_state_copy,
                    images=_images,
                    videos=_videos,
                    audio=_audio,
                    files=_files,
                    stream=False,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    metadata=run_context.metadata,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                )
                check_if_run_cancelled(member_run_response)
        except RunCancelledException:
            raise
        except Exception as e:
            task.status = TaskStatus.failed
            task.result = f"Member execution error: {e}"
            save_task_list(run_context.session_state, task_list)
            use_team_logger()
            yield f"Task [{task.id}] failed due to member execution error: {e}"
            return

        if member_run_response is not None and member_run_response.is_paused:
            _propagate_member_pause(run_response, member_agent, member_run_response)
            task.status = TaskStatus.pending
            save_task_list(run_context.session_state, task_list)
            use_team_logger()
            _post_process_member_run(member_run_response, member_agent, member_agent_task, member_session_state_copy)
            yield f"Member '{member_agent.name}' requires human input before continuing. Task [{task.id}] paused."
            return

        use_team_logger()
        _post_process_member_run(member_run_response, member_agent, member_agent_task, member_session_state_copy)

        if member_run_response is not None and member_run_response.status == RunStatus.error:
            task.status = TaskStatus.failed
            task.result = str(member_run_response.content) if member_run_response.content else "Task failed"
            save_task_list(run_context.session_state, task_list)
            yield f"Task [{task.id}] failed: {task.result}"
        elif member_run_response is not None and member_run_response.content:
            content = str(member_run_response.content)
            task.status = TaskStatus.completed
            task.result = content
            save_task_list(run_context.session_state, task_list)
            yield f"Task [{task.id}] completed. Result: {content}"
        else:
            task.status = TaskStatus.completed
            task.result = "No content returned"
            save_task_list(run_context.session_state, task_list)
            yield f"Task [{task.id}] completed with no content."

    # ------------------------------------------------------------------
    # Tool: execute_tasks_parallel (sync)
    # ------------------------------------------------------------------
    def execute_tasks_parallel(task_ids: List[str]) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Execute multiple independent tasks in parallel by delegating each to its assigned member.
        All tasks must be pending with no unresolved dependencies.

        Args:
            task_ids (list): List of task IDs to execute concurrently.
        Returns:
            str: Aggregated results from all task executions.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Validate all tasks
        tasks_to_run = []
        for tid in task_ids:
            task = task_list.get_task(tid)
            if task is None:
                yield f"Task '{tid}' not found."
                return
            if task.status not in (TaskStatus.pending, TaskStatus.in_progress):
                yield f"Task [{tid}] is {task.status.value}, cannot execute."
                return
            if not task.assignee:
                yield f"Task [{tid}] has no assignee. Assign a member_id first."
                return
            member_result = _find_member_by_id(team, task.assignee)
            if member_result is None:
                yield f"Member '{task.assignee}' not found for task [{tid}]."
                return
            tasks_to_run.append((task, member_result[1]))

        if not tasks_to_run:
            yield "No valid tasks to execute."
            return

        # Mark all in_progress
        for task_obj, _ in tasks_to_run:
            task_obj.status = TaskStatus.in_progress
        save_task_list(run_context.session_state, task_list)

        def _run_single_task(task_obj, member_agent):
            """Run a single task in a thread. Returns (task_id, member_run_response, session_state_copy, error)."""
            member_task_description = task_obj.description or task_obj.title
            member_agent_task, history = _setup_member_for_task(member_agent, member_task_description)

            use_agent_logger()
            member_session_state_copy = deepcopy(run_context.session_state)

            # Copy media lists per-thread to avoid concurrent mutation
            thread_images = list(_images)
            thread_videos = list(_videos)
            thread_audio = list(_audio)
            thread_files = list(_files)

            try:
                member_run_response = member_agent.run(
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    session_id=session.session_id,
                    session_state=member_session_state_copy,
                    images=thread_images,
                    videos=thread_videos,
                    audio=thread_audio,
                    files=thread_files,
                    stream=False,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    metadata=run_context.metadata,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                )
                return (task_obj.id, member_run_response, member_session_state_copy, member_agent_task, None)
            except RunCancelledException:
                raise
            except Exception as e:
                return (task_obj.id, None, member_session_state_copy, member_agent_task, e)

        results_text: List[str] = []
        modified_states: List[Dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=len(tasks_to_run)) as executor:
            futures = {
                executor.submit(_run_single_task, task_obj, member_agent): (task_obj, member_agent)
                for task_obj, member_agent in tasks_to_run
            }
            for future in as_completed(futures):
                task_obj, member_agent = futures[future]
                try:
                    tid, member_run, state_copy, member_task, error = future.result()
                    if state_copy is not None:
                        modified_states.append(state_copy)

                    if error is not None:
                        task_obj.status = TaskStatus.failed
                        task_obj.result = f"Member execution error: {error}"
                        results_text.append(f"Task [{tid}] failed: {error}")
                        continue

                    use_team_logger()

                    # Check HITL pause
                    if member_run is not None and member_run.is_paused:
                        _propagate_member_pause(run_response, member_agent, member_run)
                        task_obj.status = TaskStatus.pending
                        _post_process_member_run(
                            member_run,
                            member_agent,
                            member_task,
                            state_copy,
                            tool_name="execute_tasks_parallel",
                            skip_session_merge=True,
                        )
                        results_text.append(
                            f"Task [{tid}]: Member '{member_agent.name}' requires human input. Task paused."
                        )
                    elif member_run is not None and member_run.status == RunStatus.error:
                        task_obj.status = TaskStatus.failed
                        task_obj.result = str(member_run.content) if member_run.content else "Task failed"
                        _post_process_member_run(
                            member_run,
                            member_agent,
                            member_task,
                            state_copy,
                            tool_name="execute_tasks_parallel",
                            skip_session_merge=True,
                        )
                        results_text.append(f"Task [{tid}] failed: {task_obj.result}")
                    elif member_run is not None and member_run.content:
                        content = str(member_run.content)
                        task_obj.status = TaskStatus.completed
                        task_obj.result = content
                        _post_process_member_run(
                            member_run,
                            member_agent,
                            member_task,
                            state_copy,
                            tool_name="execute_tasks_parallel",
                            skip_session_merge=True,
                        )
                        results_text.append(f"Task [{tid}] completed. Result: {content}")
                    else:
                        task_obj.status = TaskStatus.completed
                        task_obj.result = "No content returned"
                        _post_process_member_run(
                            member_run,
                            member_agent,
                            member_task,
                            state_copy,
                            tool_name="execute_tasks_parallel",
                            skip_session_merge=True,
                        )
                        results_text.append(f"Task [{tid}] completed with no content.")
                except Exception as e:
                    task_obj.status = TaskStatus.failed
                    task_obj.result = f"Unexpected error: {e}"
                    results_text.append(f"Task [{task_obj.id}] failed unexpectedly: {e}")

        # Merge all modified session states
        if modified_states:
            merge_parallel_session_states(run_context.session_state, modified_states)  # type: ignore

        save_task_list(run_context.session_state, task_list)
        use_team_logger()
        yield "\n".join(results_text)

    # ------------------------------------------------------------------
    # Tool: execute_tasks_parallel (async)
    # ------------------------------------------------------------------
    async def aexecute_tasks_parallel(
        task_ids: List[str],
    ) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Execute multiple independent tasks in parallel by delegating each to its assigned member.
        All tasks must be pending with no unresolved dependencies.

        Args:
            task_ids (list): List of task IDs to execute concurrently.
        Returns:
            str: Aggregated results from all task executions.
        """
        import asyncio

        # Validate all tasks
        tasks_to_run = []
        for tid in task_ids:
            task = task_list.get_task(tid)
            if task is None:
                yield f"Task '{tid}' not found."
                return
            if task.status not in (TaskStatus.pending, TaskStatus.in_progress):
                yield f"Task [{tid}] is {task.status.value}, cannot execute."
                return
            if not task.assignee:
                yield f"Task [{tid}] has no assignee. Assign a member_id first."
                return
            member_result = _find_member_by_id(team, task.assignee)
            if member_result is None:
                yield f"Member '{task.assignee}' not found for task [{tid}]."
                return
            tasks_to_run.append((task, member_result[1]))

        if not tasks_to_run:
            yield "No valid tasks to execute."
            return

        # Mark all in_progress
        for task_obj, _ in tasks_to_run:
            task_obj.status = TaskStatus.in_progress
        save_task_list(run_context.session_state, task_list)

        async def _run_single_task_async(task_obj, member_agent):
            """Run a single task asynchronously."""
            member_task_description = task_obj.description or task_obj.title
            member_agent_task, history = _setup_member_for_task(member_agent, member_task_description)

            use_agent_logger()
            member_session_state_copy = deepcopy(run_context.session_state)

            # Copy media lists to avoid concurrent mutation across coroutines
            task_images = list(_images)
            task_videos = list(_videos)
            task_audio = list(_audio)
            task_files = list(_files)

            try:
                member_run_response = await member_agent.arun(
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    session_id=session.session_id,
                    session_state=member_session_state_copy,
                    images=task_images,
                    videos=task_videos,
                    audio=task_audio,
                    files=task_files,
                    stream=False,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    metadata=run_context.metadata,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                )
                return (task_obj.id, member_run_response, member_session_state_copy, member_agent_task, None)
            except RunCancelledException:
                raise
            except Exception as e:
                return (task_obj.id, None, member_session_state_copy, member_agent_task, e)

        # Run all tasks concurrently
        gather_results = await asyncio.gather(
            *[_run_single_task_async(task_obj, member_agent) for task_obj, member_agent in tasks_to_run],
            return_exceptions=True,
        )

        results_text: List[str] = []
        modified_states: List[Dict[str, Any]] = []

        for i, gather_result in enumerate(gather_results):
            task_obj, member_agent = tasks_to_run[i]

            if isinstance(gather_result, BaseException):
                task_obj.status = TaskStatus.failed
                task_obj.result = f"Unexpected error: {gather_result}"
                results_text.append(f"Task [{task_obj.id}] failed unexpectedly: {gather_result}")
                continue

            tid, member_run, state_copy, member_task, error = gather_result
            if state_copy is not None:
                modified_states.append(state_copy)

            if error is not None:
                task_obj.status = TaskStatus.failed
                task_obj.result = f"Member execution error: {error}"
                results_text.append(f"Task [{tid}] failed: {error}")
                continue

            use_team_logger()

            if member_run is not None and member_run.is_paused:
                _propagate_member_pause(run_response, member_agent, member_run)
                task_obj.status = TaskStatus.pending
                _post_process_member_run(
                    member_run,
                    member_agent,
                    member_task,
                    state_copy,
                    tool_name="execute_tasks_parallel",
                    skip_session_merge=True,
                )
                results_text.append(f"Task [{tid}]: Member '{member_agent.name}' requires human input. Task paused.")
            elif member_run is not None and member_run.status == RunStatus.error:
                task_obj.status = TaskStatus.failed
                task_obj.result = str(member_run.content) if member_run.content else "Task failed"
                _post_process_member_run(
                    member_run,
                    member_agent,
                    member_task,
                    state_copy,
                    tool_name="execute_tasks_parallel",
                    skip_session_merge=True,
                )
                results_text.append(f"Task [{tid}] failed: {task_obj.result}")
            elif member_run is not None and member_run.content:
                content = str(member_run.content)
                task_obj.status = TaskStatus.completed
                task_obj.result = content
                _post_process_member_run(
                    member_run,
                    member_agent,
                    member_task,
                    state_copy,
                    tool_name="execute_tasks_parallel",
                    skip_session_merge=True,
                )
                results_text.append(f"Task [{tid}] completed. Result: {content}")
            else:
                task_obj.status = TaskStatus.completed
                task_obj.result = "No content returned"
                _post_process_member_run(
                    member_run,
                    member_agent,
                    member_task,
                    state_copy,
                    tool_name="execute_tasks_parallel",
                    skip_session_merge=True,
                )
                results_text.append(f"Task [{tid}] completed with no content.")

        # Merge all modified session states
        if modified_states:
            merge_parallel_session_states(run_context.session_state, modified_states)  # type: ignore

        save_task_list(run_context.session_state, task_list)
        use_team_logger()
        yield "\n".join(results_text)

    # ------------------------------------------------------------------
    # Build and return Function list
    # ------------------------------------------------------------------
    tools: List[Function] = [
        Function.from_callable(create_task, name="create_task"),
        Function.from_callable(update_task_status, name="update_task_status"),
        Function.from_callable(list_tasks, name="list_tasks"),
        Function.from_callable(add_task_note, name="add_task_note"),
        Function.from_callable(mark_all_complete, name="mark_all_complete"),
    ]

    # Add the correct execute_task variant
    if async_mode:
        tools.append(Function.from_callable(aexecute_task, name="execute_task"))
        tools.append(Function.from_callable(aexecute_tasks_parallel, name="execute_tasks_parallel"))
    else:
        tools.append(Function.from_callable(execute_task, name="execute_task"))
        tools.append(Function.from_callable(execute_tasks_parallel, name="execute_tasks_parallel"))

    return tools
