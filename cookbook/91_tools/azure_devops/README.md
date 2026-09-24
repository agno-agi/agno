# Azure DevOps Tools

Three toolkits to integrate agents with Azure DevOps:

- `AzureDevOpsReposTools` — Git repositories (list repos, read files, file tree).
- `AzureDevOpsWikiTools` — project wikis (list wikis, read/list/search pages).
- `AzureDevOpsBoardsTools` — boards (work items, comments, sprints, fields).

## Setup

Create a personal access token (PAT) in Azure DevOps with the scopes you need
(Code, Wiki, Work Items) and set:

```bash
export AZURE_DEVOPS_ORG_URL="https://dev.azure.com/my-org"
export AZURE_DEVOPS_PAT="your-personal-access-token"
export AZURE_DEVOPS_PROJECT="MyProject"
```

Install the dependency:

```bash
pip install azure-devops
```

## Examples

```bash
python cookbook/91_tools/azure_devops/repos_tools.py
python cookbook/91_tools/azure_devops/wiki_tools.py
python cookbook/91_tools/azure_devops/boards_tools.py
```

Each toolkit accepts `organization_url`, `personal_access_token` and `project` directly,
falling back to the environment variables above. The `project` set on the toolkit is the
default; every tool also accepts an optional `project` argument to override it per call.
