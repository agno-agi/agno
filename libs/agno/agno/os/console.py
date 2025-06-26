import json
from typing import Any, Callable, Dict, List, Optional, cast
from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.db.schemas.memory import MemoryRow
from agno.document.base import Document
from agno.memory.memory import UserMemory
from agno.models.base import Model
from agno.os.interfaces.base import BaseInterface
from agno.os.managers.base import BaseManager
from agno.os.managers.knowledge.knowledge import KnowledgeManager
from agno.os.managers.memory.memory import MemoryManager
from agno.os.managers.session.session import SessionManager
from agno.os.utils import get_agent_by_id, get_team_by_id
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.team.team import Team
from agno.utils.log import log_info
from agno.workflow.workflow import Workflow


class Console(Agent):
    model: Optional[Model] = None

    _os: "AgentOS" = None
    _agents: List[Agent] = []
    _teams: List[Team] = []
    _workflows: List[Workflow] = []
    _apps: List[BaseManager] = []
    _interfaces: List[BaseInterface] = []

    _available_tags: List[str] = [
        "knowledge",
        "documents"
    ]

    def __init__(self, model: Optional[Model] = None):
        super().__init__(model=model,
                         name="Console",
                         instructions=[
                             "You are a helpful assistant for the AgentOS application.",
                             "You can answer questions and help with tasks.",
                             "When asked to run an agent, team or workflow, make sure you have enough information to do so.",
                             "You have access to the capabilities of the agents, teams, workflows that are configured. ",
                             "When given a request, consider the capabilities of the configured agents, teams, workflows, and run the appropriate agent/team/workflow with the user's request.",
                         ],
                         add_history_to_messages=True)


    def initialize(self, os: "AgentOS"):
        from agno.os.app import AgentOS
        os = cast(AgentOS, os)

        self._os = os
        self._agents = os.agents
        self._teams = os.teams
        self._workflows = os.workflows
        self._apps = os.apps
        self._interfaces = os.interfaces

        self.tools = [
            self.get_agents,
            self.get_teams,
            self.get_workflows,
        ]
        
        if self._agents:
            self.tools.append(self.run_agent)
        if self._teams:
            self.tools.append(self.run_team)
        
        _has_knowledge_manager = any(app.type == "knowledge" for app in self._apps)
        _has_memory_manager = any(app.type == "memory" for app in self._apps)
        _has_session_manager = any(app.type == "session" for app in self._apps)
        # _has_eval_manager = any(app.type == "eval" for app in self._apps)
        
        if _has_knowledge_manager:
            self.tools.extend(self.knowledge_tools_factory(knowledge_managers=[app for app in self._apps if app.type == "knowledge"]))
        if _has_memory_manager:
            self.tools.extend(self.memory_tools_factory(memory_managers=[app for app in self._apps if app.type == "memory"]))
        if _has_session_manager:
            self.tools.extend(self.session_tools_factory(session_managers=[app for app in self._apps if app.type == "session"], has_agents=bool(self._agents), has_teams=bool(self._teams)))
        
    @property
    def available_tags(self) -> List[str]:
        return self._available_tags
    
    def resolve_tags(self, tags: Optional[List[str]] = None) -> Dict[str, Callable]:
        """
        Process the tags and return the list of tools to use.
        """
        log_info(f"Resolving tags: {tags}")
        tag_context_dict = {}
        if "documents" in tags or "knowledge" in tags:
            get_docs_tool = next(tool for tool in self.tools if tool.__name__ == "get_documents")
            tag_context_dict["Knowledge"] = get_docs_tool
        
        return tag_context_dict

    def extract_tags_from_message(self, message: str) -> tuple[List[str], str]:
        """
        Extract tags from a message and return both the tags and the cleaned message.
        A tag is any string with an @ followed by a single word.
        
        Args:
            message: The original message containing tags
            
        Returns:
            tuple: (list of tags without @, cleaned message without tags)
        """
        import re
        
        # Find all tags in the message (@word)
        tag_pattern = r'@(\w+)'
        tags = re.findall(tag_pattern, message)
        
        # Remove all tags from the message
        cleaned_message = re.sub(tag_pattern, '', message).strip()
        
        return tags, cleaned_message

    def _pre_execute(self, message: str):
        
        self.context = {"Overview": self.get_os_overview}
        
        tags = []
        if "@" in message:
            tags, message = self.extract_tags_from_message(message)
        
        if tags:
            self.context.update(self.resolve_tags(tags))
        
        self.add_context = True

    async def execute(self, message: str) -> RunResponse:
        self._pre_execute(message)
        response = await self.arun(message)
        return response

    async def print(self, message: str):
        self._pre_execute(message)
        await self.aprint_response(message, show_message=False)

    ### Built In Tools ###
    async def get_agents(self) -> List[Dict[str, Any]]:
        """
        Get the list of agents available in the AgentOS
        """
        return [agent.to_dict() for agent in self._agents] if self._agents else []

    async def get_teams(self) -> List[Dict[str, Any]]:
        """
        Get the list of teams available in the AgentOS
        """
        return [team.to_dict() for team in self._teams] if self._teams else []

    async def get_workflows(self) -> List[Dict[str, Any]]:
        """
        Get the list of workflows available in the AgentOS
        """
        return [workflow.to_dict() for workflow in self._workflows] if self._workflows else []

    async def get_os_overview(self) -> Dict[str, Any]:
        """
        Get the overview of the AgentOS.
        This includes the list of agents, teams, workflows, and available apps and interfaces.
        Apps can include knowledge, memory, session, eval, etc.
        Interfaces can include whatsapp, slack, etc.
        """
        result_dict = {
            "id": self._os.os_id,
            "name": self._os.name,
            "description": self._os.description,
            "agents": await self.get_agents(),
            "teams": await self.get_teams(),
            "workflows": await self.get_workflows(),
            "apps": [app.to_dict() for app in self._apps] if self._apps else [],
            "interfaces": [interface.to_dict() for interface in self._interfaces] if self._interfaces else [],
        }
        result_dict = {k: v for k, v in result_dict.items() if v}
        return result_dict

    async def run_agent(self, agent_id: str, request: str) -> RunResponse:
        """
        Run an agent with a request.

        Args:
            agent_id: The id of the agent to run.
            request: The request to run the agent with.

        Returns:
            The run response from the agent.
        """
        agent = get_agent_by_id(agent_id, self._agents)
        if agent is None:
            raise Exception(f"Agent with id {agent_id} not found")

        return await agent.arun(message=request)

    async def run_team(self, team_id: str, request: str) -> TeamRunResponse:
        """
        Run a team with a request.

        Args:
            team_id: The id of the team to run.
            request: The request to run the team with.

        Returns:
            The run response from the team.
        """
        team = get_team_by_id(team_id, self._teams)
        if team is None:
            raise Exception(f"Team with id {team_id} not found")

        return await team.arun(message=request)

    ### Memory Tools ###
    def memory_tools_factory(self, memory_managers: List[MemoryManager]) -> List[Callable]:
        async def get_user_memories(user_id: str) -> Dict[str, Any]:
            """
            Get all the user memories from the memory base for a given user.
            Args:
                user_id: The id of the user to get memories for.

            Returns:
                The list of memories for the user.
            """
            results = []
            for memory_manager in memory_managers:
                memories = memory_manager.memory.get_user_memories(user_id=user_id)
                for memory in memories:
                    results.append(memory.to_dict())
            return results

        async def create_user_memory(user_id: str, memory: str, topics: Optional[List[str]] = None) -> Dict[str, Any]:
            """
            Create a new user memory in the memory base for a given user.
            Args:
                user_id: The id of the user to create a memory for.
                memory: The memory to create.
                topics: The topics to create the memory for.
            """
            for memory_manager in memory_managers:
                memory_manager.memory.add_user_memory(
                    memory=UserMemory(
                        memory=memory,
                        topics=topics,
                        user_id=user_id
                    )
                )
            return f"Successfully created memory for user {user_id}"

        async def update_user_memory(user_id: str, memory_id: str, memory: Optional[str] = None, topics: Optional[List[str]] = None) -> Dict[str, Any]:
            """
            Update a user memory in the memory base for a given user.
            Either provide the memory string or the topics to update the memory with.
            
            Args:
                user_id: The id of the user to update the memory for.
                memory_id: The id of the memory to update.
                memory: The memory string to update (optional).
                topics: The topics to update on the memory (optional).
            """
            for memory_manager in memory_managers:
                memory_dict = {
                    "memory": memory,
                }
                if topics:
                    memory_dict["topics"] = topics
                memory_manager.memory.db.upsert_user_memory_raw(
                    memory=MemoryRow(
                        id=memory_id, memory=memory_dict, user_id=user_id
                    )
                )
            return f"Successfully updated memory with id: {memory_id}"

        async def delete_user_memory(memory_id: str, user_id: str) -> Dict[str, Any]:
            """
            Delete a user memory from the memory base for a given user.
            Args:
                memory_id: The id of the memory to delete.
                user_id: The id of the user to delete the memory from.
            """
            for memory_manager in memory_managers:
                memory_manager.memory.delete_user_memory(memory_id=memory_id, user_id=user_id)
            return f"Successfully deleted memory with id: {memory_id}"
        
        async def delete_all_memories_for_user(user_id: str) -> Dict[str, Any]:
            """
            Delete all memories for a given user.
            Args:
                user_id: The id of the user to delete the memories from.
            """
            raise NotImplementedError("Not implemented")
        
        return [get_user_memories, create_user_memory, update_user_memory, delete_user_memory]

    ### Knowledge Tools ###
    def knowledge_tools_factory(self, knowledge_managers: List[KnowledgeManager]) -> List[Callable]:
        async def get_documents() -> Dict[str, Any]:
            """
            Get all the available documents from the knowledge base.
            """
            results = []
            for knowledge_manager in knowledge_managers:
                kb = knowledge_manager.knowledge
                # TODO: Use async
                documents = kb.get_documents()
                for document in documents:
                    # Convert DocumentV2 to DocumentResponseSchema
                    response_doc = {
                        "id": document.id,  # Generate a unique ID
                        "name": document.name,
                        "description": document.description,
                        "type": document.content.type if document.content else None,
                        "size": str(len(document.content.content)) if document.content else "0",
                        "linked_to": kb.name,
                        "metadata": document.metadata,
                        "access_count": 0,
                    }
                    results.append(response_doc)
            return results
        
        async def delete_document_by_id(document_id: str) -> Dict[str, Any]:
            """
            Delete a document from the knowledge base.
            Args:
                document_id: The id of the document to delete.
            """
            for knowledge_manager in knowledge_managers:
                kb = knowledge_manager.knowledge
                # TODO: Use async
                kb.remove_document(document_id=document_id)
            return f"Successfully deleted document with id: {document_id}"
        
        async def delete_all_documents() -> Dict[str, Any]:
            """
            Delete all documents from the knowledge base.
            """
            for knowledge_manager in knowledge_managers:
                kb = knowledge_manager.knowledge
                # TODO: Use async
                kb.remove_all_documents()
            return "Successfully deleted all documents"
        
        async def search_for_documents(query: str) -> str:
            """Use this function to search the knowledge base for information about a query

            Args:
                query: The query to search for.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            relevant_docs: List[Document] = []
            for knowledge_manager in knowledge_managers:
                kb = knowledge_manager.knowledge
                relevant_docs.extend(await kb.async_search(
                    query=query, num_documents=5
                ))

            if not relevant_docs or len(relevant_docs) == 0:
                return "No relevant documents found for query"
            
            return "\n".join([json.dumps(doc.to_dict()) for doc in relevant_docs])

        
        return [get_documents, delete_document_by_id, delete_all_documents, search_for_documents]

    ### Session Tools ###
    def session_tools_factory(self, session_managers: List[SessionManager], has_agents: bool = False, has_teams: bool = False) -> List[Callable]:
        async def get_sessions_for_agent(agent_id: str, limit: int = 20) -> Dict[str, Any]:
            """
            Get the list of sessions for an agent.
            
            Args:
                agent_id: The id of the agent to get sessions for.
                limit: The number of sessions to return (optional, default is 20).

            Returns:
                The list of sessions for the agent.
            """
            results = []
            for session_manager in session_managers:
                sessions = session_manager.db.get_sessions(session_type=SessionType.AGENT, component_id=agent_id, limit=limit)
                for session in sessions:
                    if session:
                        results.append({
                            "session_id": session.session_id,
                            "title": session.title,
                            "created_at": session.created_at
                        })
            return "\n".join([json.dumps(session) for session in results])
        
        async def get_sessions_for_team(team_id: str, limit: int = 20) -> Dict[str, Any]:
            """
            Get the list of sessions for a team.
            
            Args:
                team_id: The id of the team to get sessions for.
                limit: The number of sessions to return (optional, default is 20).

            Returns:
                The list of sessions for the team.
            """
            results = []
            for session_manager in session_managers:
                sessions = session_manager.db.get_sessions(session_type=SessionType.TEAM, component_id=team_id, limit=limit)
                for session in sessions:
                    if session:
                        results.append({
                            "session_id": session.session_id,
                            "title": session.title,
                            "created_at": session.created_at
                        })
            return "\n".join([json.dumps(session) for session in results])
        
        async def get_runs_for_agent_session(session_id: str, limit: int = 20) -> Dict[str, Any]:
            """
            Get the list of runs for an agent session.
            
            Args:
                session_id: The id of the session to get runs for.
                limit: The number of runs to return (optional, default is 20).

            Returns:
                The list of runs for the session.
            """
            results = []
            for session_manager in session_managers:
                session = session_manager.db.get_session(session_id=session_id, session_type=SessionType.AGENT)
                if session:
                    for run in session.runs:
                        if run:
                            results.append(run.to_dict())
            return "\n".join([json.dumps(run) for run in results])
        
        async def get_runs_for_team_session(session_id: str, limit: int = 20) -> Dict[str, Any]:
            """
            Get the list of runs for a team session.
            
            Args:
                session_id: The id of the session to get runs for.
                limit: The number of runs to return (optional, default is 20).

            Returns:
                The list of runs for the session.
            """
            results = []
            for session_manager in session_managers:
                session = session_manager.db.get_session(session_id=session_id, session_type=SessionType.TEAM)
                if session:
                    for run in session.runs:
                        if run:
                            results.append(run.to_dict())
            return "\n".join([json.dumps(run) for run in results])
        
        tools = []
        if has_agents:
            tools.append(get_sessions_for_agent)
            tools.append(get_runs_for_agent_session)
        if has_teams:
            tools.append(get_sessions_for_team)
            tools.append(get_runs_for_team_session)
        
        return tools
    