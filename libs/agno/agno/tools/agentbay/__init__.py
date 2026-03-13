"""
AgentBay Tools for Agno.

Cloud computing toolkit providing comprehensive AgentBay integration.
"""

try:
    from agentbay import AgentBay, CreateSessionParams
except ImportError:
    raise ImportError("`agentbay` not installed. Please install using `pip install wuying-agentbay-sdk`")

from .session_manager import AgentBaySessionManager
from .toolkit import AgentBayTools

# Convenient alias for easier imports
Tools = AgentBayTools

__version__ = "0.1.0"
__all__ = [
    "AgentBayTools",
    "AgentBaySessionManager",
    "Tools",
    "SessionManager",
]


class SessionManager:
    """Manager for multiple AgentBay sessions."""

    def __init__(self) -> None:
        self.agent_bay = AgentBay()
        self.sessions: dict = {}

    def create_session(self, session_name: str, params: CreateSessionParams) -> None:
        """Create a new session and store it."""
        result = self.agent_bay.create(params)
        if result.success and result.session:
            self.sessions[session_name] = result.session
            print(f"Session '{session_name}' created with ID: {result.session.session_id}")
        else:
            print(f"Failed to create session '{session_name}': {result.error_message}")

    def get_session(self, session_name: str):
        """Retrieve a session by name."""
        return self.sessions.get(session_name)

    def share_data_via_file(
        self,
        source_session_name: str,
        target_session_name: str,
        file_path: str,
        content: str,
    ) -> None:
        """Share data between sessions using the file system."""
        source_session = self.get_session(source_session_name)
        target_session = self.get_session(target_session_name)

        if source_session and target_session:
            write_result = source_session.file_system.write_file(file_path, content)
            if write_result.success:
                print(f"File written in session '{source_session_name}' at path: {file_path}")

                read_result = target_session.file_system.read_file(file_path)
                if read_result.success:
                    print(f"File read in session '{target_session_name}': {read_result.content}")
                else:
                    print(f"Failed to read file in session '{target_session_name}': {read_result.error_message}")
            else:
                print(f"Failed to write file in session '{source_session_name}': {write_result.error_message}")
        else:
            print("Source or target session not found.")


if __name__ == "__main__":
    manager = SessionManager()

    manager.create_session("dev-session", CreateSessionParams(environment="development"))
    manager.create_session("test-session", CreateSessionParams(environment="testing"))

    manager.share_data_via_file(
        source_session_name="dev-session",
        target_session_name="test-session",
        file_path="/tmp/shared_data.txt",
        content="This is shared data between sessions.",
    )
