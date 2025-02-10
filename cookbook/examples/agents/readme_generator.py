from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.github import GithubTools
from agno.tools.local_file_system import LocalFileSystemTools

readme_gen_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    name="Readme Generator Agent",
    tools=[GithubTools(), LocalFileSystemTools()],
    markdown=True,
    debug_mode=True,
    instructions=[
        "You are readme generator agent",
        "You'll be given repository url or repository name from user."
        "You'll use the `get_repository` tool to get the repository details."
        "You have to pass the repo_name as argument to the tool. It should be in the format of owner/repo_name. If given url extract owner/repo_name from it."
        "Also call the `get_repository_languages` tool to get the languages used in the repository."
        "Write a useful README for a open source project, including how to clone and install the project, run the project etc. Also add badges for the license, size of the repo, etc"
        "Don't include the project's languages-used in the README"
        "Write the produced README to the local filesystem",
    ],
)

readme_gen_agent.print_response(
    "Get details of https://github.com/agno-agi/agno", markdown=True
)
