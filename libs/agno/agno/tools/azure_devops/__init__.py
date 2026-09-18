__all__ = [
    "AzureDevOpsBaseTools",
    "AzureDevOpsBoardsTools",
    "AzureDevOpsReposTools",
    "AzureDevOpsWikiTools",
]


def __getattr__(name: str):
    if name == "AzureDevOpsBaseTools":
        from agno.tools.azure_devops.base import AzureDevOpsBaseTools

        return AzureDevOpsBaseTools
    if name == "AzureDevOpsBoardsTools":
        from agno.tools.azure_devops.boards import AzureDevOpsBoardsTools

        return AzureDevOpsBoardsTools
    if name == "AzureDevOpsReposTools":
        from agno.tools.azure_devops.repos import AzureDevOpsReposTools

        return AzureDevOpsReposTools
    if name == "AzureDevOpsWikiTools":
        from agno.tools.azure_devops.wiki import AzureDevOpsWikiTools

        return AzureDevOpsWikiTools
    raise AttributeError(f"module 'agno.tools.azure_devops' has no attribute {name!r}")
