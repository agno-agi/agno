"""
Custom Stores — Extending the System
=====================================
Build your own learning stores by implementing the LearningStore protocol.

The built-in stores (UserProfile, SessionContext, Learnings) cover common
cases, but you might need domain-specific learning:
- Project context for a project management agent
- Tool preferences for a coding assistant
- Conversation style for a writing agent

This cookbook demonstrates:
1. The LearningStore protocol
2. Simple custom store example
3. Project context store
4. Tool preference store
5. Registering custom stores
6. Combining with built-in stores
7. Custom store with tools
8. Async support

Run this example:
    python cookbook/learning/09_custom_stores.py
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import LearningMachine
from agno.learn.stores.protocol import LearningStore
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType
from rich.pretty import pprint

# =============================================================================
# Setup
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o-mini")

knowledge = Knowledge(
    name="Custom Stores Test KB",
    vector_db=PgVector(
        db_url=db_url,
        table_name="custom_stores_test",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


# =============================================================================
# Test 1: The LearningStore Protocol
# =============================================================================


def test_protocol_overview():
    """
    Understanding the LearningStore protocol.
    """
    print("\n" + "=" * 60)
    print("TEST 1: The LearningStore Protocol")
    print("=" * 60)

    print("""
    Every custom store must implement the LearningStore protocol:
    
    ┌─────────────────────────────────────────────────────────────┐
    │ class LearningStore(Protocol):                              │
    │                                                             │
    │   @property                                                 │
    │   def learning_type(self) -> str:                          │
    │       '''Unique identifier for this store type'''           │
    │                                                             │
    │   def recall(self, **kwargs) -> Optional[Any]:             │
    │       '''Retrieve data from storage'''                      │
    │                                                             │
    │   async def arecall(self, **kwargs) -> Optional[Any]:      │
    │       '''Async version of recall'''                         │
    │                                                             │
    │   def process(self, **kwargs) -> None:                     │
    │       '''Extract and save from conversations'''             │
    │                                                             │
    │   async def aprocess(self, **kwargs) -> None:              │
    │       '''Async version of process'''                        │
    │                                                             │
    │   def build_context(self, data: Any) -> str:               │
    │       '''Format data for system prompt'''                   │
    │                                                             │
    │   def get_tools(self, **kwargs) -> List[Callable]:         │
    │       '''Return tools for agent'''                          │
    │                                                             │
    │   async def aget_tools(self, **kwargs) -> List[Callable]:  │
    │       '''Async version of get_tools'''                      │
    │                                                             │
    │   @property                                                 │
    │   def was_updated(self) -> bool:                           │
    │       '''Did the last operation change state?'''            │
    └─────────────────────────────────────────────────────────────┘
    
    Key points:
    • learning_type: Must be unique across all stores
    • recall/process: Core data flow
    • build_context: Format for LLM consumption
    • get_tools: Optional agent tools
    • was_updated: State tracking for LearningMachine
    """)

    print("✅ Protocol overview complete!")


# =============================================================================
# Test 2: Simple Custom Store
# =============================================================================


@dataclass
class SimpleCounterStore(LearningStore):
    """
    The simplest possible custom store: just counts interactions.
    """

    counts: Dict[str, int] = field(default_factory=dict)
    _updated: bool = field(default=False, init=False)

    @property
    def learning_type(self) -> str:
        return "interaction_counter"

    def recall(self, user_id: Optional[str] = None, **kwargs) -> Optional[int]:
        if user_id:
            return self.counts.get(user_id, 0)
        return sum(self.counts.values())

    async def arecall(self, **kwargs) -> Optional[int]:
        return self.recall(**kwargs)

    def process(self, user_id: Optional[str] = None, **kwargs) -> None:
        if user_id:
            self.counts[user_id] = self.counts.get(user_id, 0) + 1
            self._updated = True

    async def aprocess(self, **kwargs) -> None:
        self.process(**kwargs)

    def build_context(self, data: Any) -> str:
        if data is None:
            return ""
        return f"<interaction_count>{data}</interaction_count>"

    def get_tools(self, **kwargs) -> List[Callable]:
        return []

    async def aget_tools(self, **kwargs) -> List[Callable]:
        return []

    @property
    def was_updated(self) -> bool:
        return self._updated

    def __repr__(self) -> str:
        return f"SimpleCounterStore(users={len(self.counts)}, total={sum(self.counts.values())})"


def test_simple_store():
    """
    Test the simplest custom store.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Simple Custom Store")
    print("=" * 60)

    store = SimpleCounterStore()

    # Process some interactions
    store.process(user_id="alice")
    store.process(user_id="alice")
    store.process(user_id="bob")

    print(f"\n📊 Store state: {store}")
    print(f"   Alice's count: {store.recall(user_id='alice')}")
    print(f"   Bob's count: {store.recall(user_id='bob')}")
    print(f"   Total count: {store.recall()}")

    # Build context
    alice_count = store.recall(user_id="alice")
    context = store.build_context(alice_count)
    print(f"\n📝 Context for Alice: {context}")

    print("\n✅ Simple custom store works!")


# =============================================================================
# Test 3: Project Context Store
# =============================================================================


@dataclass
class Project:
    """A project with metadata."""

    id: str
    name: str
    description: str
    status: str = "active"
    tech_stack: List[str] = field(default_factory=list)
    current_phase: str = "planning"
    team_members: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "tech_stack": self.tech_stack,
            "current_phase": self.current_phase,
            "team_members": self.team_members,
        }


@dataclass
class ProjectContextStore(LearningStore):
    """
    Tracks project context for a project management agent.

    Use case: An agent that helps manage software projects needs to
    know which project the user is currently working on.
    """

    projects: Dict[str, Project] = field(default_factory=dict)
    user_active_project: Dict[str, str] = field(default_factory=dict)
    _updated: bool = field(default=False, init=False)

    @property
    def learning_type(self) -> str:
        return "project_context"

    def recall(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[Project]:
        # If project_id specified, return that project
        if project_id:
            return self.projects.get(project_id)

        # If user_id specified, return their active project
        if user_id:
            active_id = self.user_active_project.get(user_id)
            if active_id:
                return self.projects.get(active_id)

        return None

    async def arecall(self, **kwargs) -> Optional[Project]:
        return self.recall(**kwargs)

    def process(self, **kwargs) -> None:
        # Could extract project mentions from conversation
        # For simplicity, we'll use manual methods
        pass

    async def aprocess(self, **kwargs) -> None:
        pass

    def build_context(self, data: Any) -> str:
        if not data:
            return ""

        project = data
        return f"""<project_context>
Current Project: {project.name}
Description: {project.description}
Status: {project.status}
Phase: {project.current_phase}
Tech Stack: {", ".join(project.tech_stack)}
Team: {", ".join(project.team_members)}
</project_context>"""

    def get_tools(self, user_id: Optional[str] = None, **kwargs) -> List[Callable]:
        def set_active_project(project_id: str) -> str:
            """Set the active project for the current user."""
            if project_id not in self.projects:
                return f"Project '{project_id}' not found."
            if user_id:
                self.user_active_project[user_id] = project_id
                self._updated = True
                project = self.projects[project_id]
                return f"Active project set to: {project.name}"
            return "No user context available."

        def list_projects() -> str:
            """List all available projects."""
            if not self.projects:
                return "No projects found."
            lines = ["Available projects:"]
            for pid, proj in self.projects.items():
                lines.append(f"  - {pid}: {proj.name} ({proj.status})")
            return "\n".join(lines)

        return [set_active_project, list_projects]

    async def aget_tools(self, **kwargs) -> List[Callable]:
        return self.get_tools(**kwargs)

    @property
    def was_updated(self) -> bool:
        return self._updated

    # Custom methods
    def add_project(self, project: Project) -> None:
        self.projects[project.id] = project
        self._updated = True

    def __repr__(self) -> str:
        return f"ProjectContextStore(projects={len(self.projects)})"


def test_project_store():
    """
    Test the project context store.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Project Context Store")
    print("=" * 60)

    store = ProjectContextStore()

    # Add some projects
    store.add_project(
        Project(
            id="proj_001",
            name="Customer Portal",
            description="Web app for customer self-service",
            tech_stack=["React", "FastAPI", "PostgreSQL"],
            current_phase="development",
            team_members=["Alice", "Bob"],
        )
    )

    store.add_project(
        Project(
            id="proj_002",
            name="Mobile App v2",
            description="Next-gen mobile experience",
            tech_stack=["React Native", "GraphQL"],
            current_phase="planning",
            team_members=["Carol", "Dave"],
        )
    )

    print(f"\n📊 Store state: {store}")

    # Set active project for a user
    tools = store.get_tools(user_id="alice")
    set_active = tools[0]
    list_projects = tools[1]

    print(f"\n🔧 Available tools: {[t.__name__ for t in tools]}")

    # List projects
    print(f"\n{list_projects()}")

    # Set active project
    result = set_active("proj_001")
    print(f"\n📝 {result}")

    # Recall and build context
    project = store.recall(user_id="alice")
    context = store.build_context(project)

    print("\n📝 Context for Alice:")
    print(context)

    print("\n✅ Project context store works!")


# =============================================================================
# Test 4: Tool Preference Store
# =============================================================================


@dataclass
class ToolPreferences:
    """User's tool preferences."""

    preferred_editor: str = "vscode"
    preferred_terminal: str = "bash"
    preferred_package_manager: str = "npm"
    code_style: str = "verbose"
    test_framework: str = "pytest"

    def to_dict(self) -> dict:
        return {
            "preferred_editor": self.preferred_editor,
            "preferred_terminal": self.preferred_terminal,
            "preferred_package_manager": self.preferred_package_manager,
            "code_style": self.code_style,
            "test_framework": self.test_framework,
        }


@dataclass
class ToolPreferenceStore(LearningStore):
    """
    Tracks tool preferences for a coding assistant.

    Use case: A coding agent that adapts its suggestions to user's
    preferred tools and coding style.
    """

    preferences: Dict[str, ToolPreferences] = field(default_factory=dict)
    _updated: bool = field(default=False, init=False)

    @property
    def learning_type(self) -> str:
        return "tool_preferences"

    def recall(
        self, user_id: Optional[str] = None, **kwargs
    ) -> Optional[ToolPreferences]:
        if user_id:
            return self.preferences.get(user_id)
        return None

    async def arecall(self, **kwargs) -> Optional[ToolPreferences]:
        return self.recall(**kwargs)

    def process(
        self,
        messages: Optional[List[Message]] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract tool preferences from conversation."""
        if not messages or not user_id:
            return

        # Simple extraction logic (in production, use LLM)
        text = " ".join(m.content or "" for m in messages).lower()

        prefs = self.preferences.get(user_id, ToolPreferences())

        # Detect editor preferences
        if "vim" in text or "neovim" in text:
            prefs.preferred_editor = "vim"
            self._updated = True
        elif "emacs" in text:
            prefs.preferred_editor = "emacs"
            self._updated = True

        # Detect package manager
        if "yarn" in text:
            prefs.preferred_package_manager = "yarn"
            self._updated = True
        elif "pnpm" in text:
            prefs.preferred_package_manager = "pnpm"
            self._updated = True

        # Detect code style
        if "concise" in text or "minimal" in text:
            prefs.code_style = "concise"
            self._updated = True

        if self._updated:
            self.preferences[user_id] = prefs

    async def aprocess(self, **kwargs) -> None:
        self.process(**kwargs)

    def build_context(self, data: Any) -> str:
        if not data:
            return ""

        prefs = data
        return f"""<tool_preferences>
Editor: {prefs.preferred_editor}
Terminal: {prefs.preferred_terminal}
Package Manager: {prefs.preferred_package_manager}
Code Style: {prefs.code_style}
Test Framework: {prefs.test_framework}
</tool_preferences>"""

    def get_tools(self, user_id: Optional[str] = None, **kwargs) -> List[Callable]:
        def set_preference(setting: str, value: str) -> str:
            """Set a tool preference. Settings: editor, terminal, package_manager, code_style, test_framework."""
            if not user_id:
                return "No user context."

            prefs = self.preferences.get(user_id, ToolPreferences())

            setting_map = {
                "editor": "preferred_editor",
                "terminal": "preferred_terminal",
                "package_manager": "preferred_package_manager",
                "code_style": "code_style",
                "test_framework": "test_framework",
            }

            if setting not in setting_map:
                return f"Unknown setting: {setting}. Valid: {list(setting_map.keys())}"

            setattr(prefs, setting_map[setting], value)
            self.preferences[user_id] = prefs
            self._updated = True

            return f"Set {setting} to '{value}'"

        return [set_preference]

    async def aget_tools(self, **kwargs) -> List[Callable]:
        return self.get_tools(**kwargs)

    @property
    def was_updated(self) -> bool:
        return self._updated

    def __repr__(self) -> str:
        return f"ToolPreferenceStore(users={len(self.preferences)})"


def test_tool_preference_store():
    """
    Test the tool preference store.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Tool Preference Store")
    print("=" * 60)

    store = ToolPreferenceStore()

    # Process a conversation that reveals preferences
    messages = [
        Message(role="user", content="I use vim and yarn for my projects."),
        Message(role="assistant", content="Great choices!"),
        Message(role="user", content="I prefer concise code, no verbose comments."),
    ]

    store.process(messages=messages, user_id="developer@example.com")

    print(f"\n📊 Store state: {store}")
    print(f"🔄 was_updated: {store.was_updated}")

    # Recall and build context
    prefs = store.recall(user_id="developer@example.com")
    if prefs:
        print("\n📋 Extracted preferences:")
        pprint(prefs.to_dict())

        context = store.build_context(prefs)
        print("\n📝 Context for system prompt:")
        print(context)

    # Use the tool
    tools = store.get_tools(user_id="developer@example.com")
    set_pref = tools[0]
    result = set_pref("test_framework", "jest")
    print(f"\n🔧 Tool result: {result}")

    print("\n✅ Tool preference store works!")


# =============================================================================
# Test 5: Registering Custom Stores
# =============================================================================


def test_register_custom_stores():
    """
    Register custom stores with LearningMachine.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Registering Custom Stores")
    print("=" * 60)

    # Create custom stores
    project_store = ProjectContextStore()
    tool_store = ToolPreferenceStore()

    # Populate with some data
    project_store.add_project(
        Project(
            id="demo",
            name="Demo Project",
            description="A demo project",
            tech_stack=["Python"],
        )
    )

    # Register with LearningMachine
    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        # Disable built-in stores for this test
        user_profile=False,
        session_context=False,
        learnings=False,
        # Register custom stores
        custom_stores={
            "project": project_store,
            "tools": tool_store,
        },
    )

    print(f"\n📊 LearningMachine: {learning}")
    print(f"\n📋 Registered stores: {list(learning.stores.keys())}")

    # The stores are now accessible
    for name, store in learning.stores.items():
        print(f"   {name}: {store}")

    print("\n✅ Custom stores registered!")


# =============================================================================
# Test 6: Combining with Built-in Stores
# =============================================================================


def test_combined_stores():
    """
    Use custom stores alongside built-in stores.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Combining with Built-in Stores")
    print("=" * 60)

    # Create custom store
    project_store = ProjectContextStore()
    project_store.add_project(
        Project(
            id="main",
            name="Main Project",
            description="The primary project",
            tech_stack=["Python", "React"],
            current_phase="development",
        )
    )

    # Create LearningMachine with both
    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        # Enable some built-in stores
        user_profile=True,
        session_context=True,
        learnings=False,
        # Add custom store
        custom_stores={"project": project_store},
    )

    print(f"\n📋 All stores: {list(learning.stores.keys())}")

    # Set active project
    project_store.user_active_project["test_user"] = "main"

    # Build combined context
    context = learning.build_context(
        user_id="test_user",
        session_id="test_session",
        message="What should I work on?",
    )

    print(f"\n📝 Combined context ({len(context)} chars):")
    print("-" * 40)
    # Show excerpt
    print(context[:600] if len(context) > 600 else context)
    print("-" * 40)

    # Get combined tools
    tools = learning.get_tools(user_id="test_user")
    print(f"\n🔧 Combined tools ({len(tools)}):")
    for tool in tools:
        print(f"   - {getattr(tool, '__name__', str(tool))}")

    print("\n✅ Custom and built-in stores work together!")


# =============================================================================
# Test 7: Custom Store with Async
# =============================================================================


@dataclass
class AsyncExampleStore(LearningStore):
    """
    Example showing async implementations.
    """

    data: Dict[str, str] = field(default_factory=dict)
    _updated: bool = field(default=False, init=False)

    @property
    def learning_type(self) -> str:
        return "async_example"

    def recall(self, key: Optional[str] = None, **kwargs) -> Optional[str]:
        if key:
            return self.data.get(key)
        return None

    async def arecall(self, key: Optional[str] = None, **kwargs) -> Optional[str]:
        # In production, this might hit an async database
        # await asyncio.sleep(0)  # Simulate async operation
        return self.recall(key=key, **kwargs)

    def process(self, **kwargs) -> None:
        pass

    async def aprocess(self, **kwargs) -> None:
        # await asyncio.sleep(0)  # Simulate async operation
        self.process(**kwargs)

    def build_context(self, data: Any) -> str:
        return f"<async_data>{data}</async_data>" if data else ""

    def get_tools(self, **kwargs) -> List[Callable]:
        return []

    async def aget_tools(self, **kwargs) -> List[Callable]:
        return []

    @property
    def was_updated(self) -> bool:
        return self._updated

    def __repr__(self) -> str:
        return f"AsyncExampleStore(keys={len(self.data)})"


def test_async_store():
    """
    Test async store methods.
    """
    print("\n" + "=" * 60)
    print("TEST 7: Async Support")
    print("=" * 60)

    store = AsyncExampleStore()
    store.data["test"] = "async value"

    # Sync access
    result = store.recall(key="test")
    print(f"\n📊 Sync recall: {result}")

    # Async access would work in an async context:
    # result = await store.arecall(key="test")

    print("""
    Async methods follow the same pattern:
    
    • arecall() — Async version of recall()
    • aprocess() — Async version of process()
    • aget_tools() — Async version of get_tools()
    
    LearningMachine automatically uses the right version:
    • learning.recall() calls store.recall()
    • await learning.arecall() calls store.arecall()
    """)

    print("\n✅ Async support documented!")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🔧 Custom Stores — Extending the System")
    print("=" * 60)

    # Run all tests
    test_protocol_overview()
    test_simple_store()
    test_project_store()
    test_tool_preference_store()
    test_register_custom_stores()
    test_combined_stores()
    test_async_store()

    # Summary
    print("\n" + "=" * 60)
    print("✅ All tests complete!")
    print("=" * 60)
    print("""
Key takeaways:

1. **Protocol**: Implement LearningStore with 8 methods

2. **learning_type**: Unique string identifier for your store

3. **Core Methods**:
   - recall() — Get data
   - process() — Extract from conversations
   - build_context() — Format for LLM

4. **Optional**: get_tools() for agent tools

5. **Registration**: Pass to LearningMachine via custom_stores={}

6. **Combining**: Custom stores work alongside built-in ones

7. **Async**: Implement arecall/aprocess/aget_tools for async support

Example custom stores:
• ProjectContextStore — Track active project
• ToolPreferenceStore — Remember tool choices
• CounterStore — Track interaction counts
""")
