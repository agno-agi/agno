"""
File Tools - File System Operations and Management

This example demonstrates how to use FileTools for file operations
including reading, writing, searching files, and searching file contents.
Shows enable_ flag patterns for selective function access.
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import DEFAULT_EXCLUDE_PATTERNS, FileTools

EXCLUSION_SANDBOX = Path("tmp/file_tools_exclusions")


def setup_exclusion_sandbox() -> None:
    EXCLUSION_SANDBOX.mkdir(parents=True, exist_ok=True)

    (EXCLUSION_SANDBOX / "main.py").write_text("def hello():\n    return 'world'\n")
    (EXCLUSION_SANDBOX / "README.md").write_text("# My Project\n\nDoes a thing.\n")

    site_pkg = (
        EXCLUSION_SANDBOX
        / ".venv"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "requests"
    )
    site_pkg.mkdir(parents=True, exist_ok=True)
    (site_pkg / "__init__.py").write_text("__version__ = '2.31.0'\n")
    (site_pkg / "api.py").write_text("def get(url):\n    pass\n")

    git_dir = EXCLUSION_SANDBOX / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: All functions enabled (default behavior)
agent_full = Agent(
    tools=[
        FileTools(Path("tmp/file"))
    ],  # All functions enabled by default, except file deletion
    description="You are a comprehensive file management assistant with all file operation capabilities.",
    instructions=[
        "Help users with all file operations including read, write, search, and management",
        "Create, modify, and organize files and directories",
        "Provide clear feedback on file operations",
        "Ensure file paths and operations are valid",
    ],
    markdown=True,
)

# Example 2: Enable only file reading and searching
agent_readonly = Agent(
    tools=[
        FileTools(
            Path("tmp/file"),
            enable_read_file=True,
            enable_search_files=True,
            enable_list_files=True,
        )
    ],
    description="You are a file reader focused on accessing and searching existing files.",
    instructions=[
        "Read and search through existing files",
        "List file contents and directory structures",
        "Cannot create, modify, or delete files",
        "Focus on information retrieval and file exploration",
    ],
    markdown=True,
)

# Example 3: Enable all functions using 'all=True' pattern
agent_comprehensive = Agent(
    tools=[FileTools(Path("tmp/file"), all=True)],
    description="You are a full-featured file system manager with all capabilities enabled.",
    instructions=[
        "Perform comprehensive file system operations",
        "Manage complete file lifecycles including creation, modification, and deletion",
        "Support advanced file organization and processing workflows",
        "Provide end-to-end file management solutions",
    ],
    markdown=True,
)

# Example 4: Write-only operations (for content creation)
agent_writer = Agent(
    tools=[
        FileTools(
            Path("tmp/file"),
            enable_save_file=True,
            enable_read_file=False,  # Disable file reading
            enable_read_file_chunk=False,  # Disable reading in chunks as well
            enable_search_files=False,  # Disable file searching
        )
    ],
    description="You are a content creator focused on writing and organizing new files.",
    instructions=[
        "Create new files and directories",
        "Generate and save content to files",
        "Cannot read existing files or search directories",
        "Focus on content creation and file organization",
    ],
    markdown=True,
)

# Example 5: Content search agent using enable_search_content
# search_content lets the agent grep through file contents (case-insensitive)
# for a query string, returning matching files with snippets.
agent_content_search = Agent(
    tools=[
        FileTools(
            Path("tmp/file"),
            enable_read_file=True,
            enable_search_content=True,
            enable_list_files=True,
            enable_save_file=False,
        )
    ],
    description="You are a content search specialist that finds information within files.",
    instructions=[
        "Search through file contents to find relevant information",
        "Use search_content to locate files containing specific terms",
        "Summarize the matches and provide context from the snippets",
    ],
    markdown=True,
)

# Example 6: Default exclusions skip noise directories (.venv, .git, __pycache__,
# node_modules, build artifacts, etc.) so agents don't waste context on installed
# packages or VCS metadata. See DEFAULT_EXCLUDE_PATTERNS for the full list.
agent_default_exclusions = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        FileTools(
            base_dir=EXCLUSION_SANDBOX,
            enable_list_files=True,
            enable_search_files=True,
            enable_search_content=True,
        )
    ],
    description="You help users explore a project, skipping build and dependency noise.",
    instructions=[
        "Use list_files and search_content to answer questions about the project",
    ],
    markdown=True,
)

# Example 7: Custom exclusions - start from DEFAULT_EXCLUDE_PATTERNS and remove
# the entries you want visible. Future additions to the default list apply
# automatically. Here we keep the defaults but unhide .venv so the agent can
# inspect installed packages.
exclude_without_venv = [p for p in DEFAULT_EXCLUDE_PATTERNS if p != ".venv"]

agent_can_read_venv = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        FileTools(
            base_dir=EXCLUSION_SANDBOX,
            exclude_patterns=exclude_without_venv,
            enable_list_files=True,
            enable_search_files=True,
            enable_search_content=True,
        )
    ],
    description="You inspect installed Python packages to answer version and source questions.",
    instructions=[
        "Use search_content and search_files to look inside .venv when asked",
        "Report package versions and the file path where you found them",
    ],
    markdown=True,
)

# Example 8: Full opt-out with exclude_patterns=[]. Every file becomes visible,
# including .git internals. Use only when you need forensic access to the tree.
agent_sees_everything = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        FileTools(
            base_dir=EXCLUSION_SANDBOX,
            exclude_patterns=[],
            enable_list_files=True,
            enable_search_files=True,
        )
    ],
    description="You audit the full project tree, including hidden and ignored directories.",
    instructions=[
        "Return the complete file inventory when asked",
    ],
    markdown=True,
)

# Example usage

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Full File Management Example ===")
    agent_full.print_response(
        "What is the most advanced LLM currently? Save the answer to a file.",
        markdown=True,
    )

    print("\n=== Read-Only File Operations Example ===")
    agent_readonly.print_response(
        "Search for all files in the directory and list their names and sizes",
        markdown=True,
    )

    print("\n=== File Writing Example ===")
    agent_writer.print_response(
        "Create a summary of Python best practices and save it to 'python_guide.txt'",
        markdown=True,
    )

    print("\n=== File Search Example ===")
    agent_full.print_response(
        "Search for all files which have an extension '.txt' and save the answer to a new file named 'all_txt_files.txt'",
        markdown=True,
    )

    print("\n=== Content Search Example ===")
    agent_content_search.print_response(
        "Search inside all files for the word 'Python' and summarize what you find",
        markdown=True,
    )

    setup_exclusion_sandbox()

    print("\n=== Default Exclusions Example (hides .venv, .git, etc.) ===")
    agent_default_exclusions.print_response(
        "List every file in this project and tell me what the project does.",
        markdown=True,
    )

    print("\n=== Custom Exclusions Example (inspect .venv) ===")
    agent_can_read_venv.print_response(
        "Find the version of the `requests` package installed in this project. "
        "Show the file path where you found the version string.",
        markdown=True,
    )

    print("\n=== No Exclusions Example (see .git internals) ===")
    agent_sees_everything.print_response(
        "List every single file in the project, including git internals.",
        markdown=True,
    )
