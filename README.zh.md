<div align="center" id="top">
  <a href="https://agno.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg">
      <img src="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg" alt="Agno">
    </picture>
  </a>
</div>

<p align="center">
  构建、运行和管理大规模智能体软件（Agentic Software）。
</p>

<div align="center">
  <a href="https://docs.agno.com">文档</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://github.com/agno-agi/agno/tree/main/cookbook">Cookbook</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://docs.agno.com/first-agent">快速入门</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://www.agno.com/discord">Discord</a>
</div>

<p align="center">
  <strong>中文</strong> | <a href="README.md">English</a>
</p>

## 什么是 Agno

Agno 是智能体软件（Agentic Software）的运行时（Runtime）。它可以帮助您构建智能体（Agents）、团队（Teams）和工作流（Workflows），并将它们作为可扩展的服务运行，同时在生产环境中进行监控和管理。

| 层级 | 功能 |
|-------|--------------|
| **框架 (Framework)** | 利用记忆、知识库、护栏（Guardrails）以及 100 多个集成插件，构建智能体、团队和工作流。 |
| **运行时 (Runtime)** | 使用无状态、会话隔离的 FastAPI 后端，在生产环境中提供系统服务。 |
| **控制平面 (Control Plane)** | 使用 [AgentOS UI](https://os.agno.com) 测试、监控和管理您的系统。 |

## 快速开始

仅需约 20 行代码，即可构建一个具备状态、能够使用工具的智能体，并将其作为生产级 API 提供服务。

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

agno_assist = Agent(
    name="Agno Assist",
    model=Claude(id="claude-sonnet-4-6"),
    db=SqliteDb(db_file="agno.db"),
    tools=[MCPTools(url="https://docs.agno.com/mcp")],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(agents=[agno_assist], tracing=True)
app = agent_os.get_app()
```

运行：

```bash
export ANTHROPIC_API_KEY="***"

uvx --python 3.12 \
  --with "agno[os]" \
  --with anthropic \
  --with mcp \
  fastapi dev agno_assist.py
```

在约 20 行代码中，您可以获得：
- 一个支持流式响应的有状态智能体
- 基于用户和会话的隔离
- 位于 http://localhost:8000 的生产级 API
- 原生追踪（Tracing）

连接到 [AgentOS UI](https://os.agno.com) 来监控、管理和测试您的智能体。

1. 打开 [os.agno.com](https://os.agno.com) 并登录。
2. 在顶部导航栏点击 **"Add new OS"**。
3. 选择 **"Local"** 以连接到本地 AgentOS。
4. 输入您的端点 URL（默认：`http://localhost:8000`）。
5. 命名为 "Local AgentOS"。
6. 点击 **"Connect"**。

https://github.com/user-attachments/assets/75258047-2471-4920-8874-30d68c492683

打开 Chat，选择您的智能体，然后提问：

> 什么是 Agno？

智能体会从 Agno MCP 服务器检索上下文，并给出基于事实的回答。

https://github.com/user-attachments/assets/24c28d28-1d17-492c-815d-810e992ea8d2

您可以将完全相同的架构用于在生产环境中运行多智能体系统。

## 为什么选择 Agno？

智能体软件引入了三个根本性的转变。

### 全新的交互模型

传统软件接收请求并返回响应。而智能体则实时流式传输推理过程、工具调用和结果。它们可以在执行过程中暂停、等待审批并稍后恢复。

Agno 将流式传输和长时运行的执行视为一等公民行为。

### 全新的治理模型

传统系统执行预先编写好的决策逻辑。智能体则是动态选择动作。有些动作风险较低，有些需要用户审批，有些则需要管理权限。

Agno 允许您在智能体定义中明确“由谁决定什么”，包括：

- 审批工作流
- 人在回路（Human-in-the-loop）
- 审计日志
- 运行时强制执行

### 全新的信任模型

传统系统的设计目标是可预测性，每条执行路径都是预先定义的。智能体则在执行路径中引入了概率推理。

Agno 将信任直接内置于引擎本身：

- 在执行过程中运行护栏（Guardrails）
- 将评估（Evaluations）集成到智能体循环中
- 追踪（Traces）和审计日志是系统核心

## 为生产环境而生

Agno 运行在您的基础设施中，而非我们的。

- 无状态、可水平扩展的运行时。
- 50 多个 API 和后台执行。
- 基于用户和会话的隔离。
- 运行时审批强制执行。
- 原生追踪和完整的可审计性。
- 会话、记忆、知识和追踪均存储在您的数据库中。

您拥有系统，您拥有数据，您定义规则。

## 您可以构建什么

Agno 驱动了许多基于上述原语构建的真实智能体系统。

- [**Pal →**](https://github.com/agno-agi/pal) 一个能学习您偏好的个人智能体。
- [**Dash →**](https://github.com/agno-agi/dash) 一个基于六层上下文的自学习数据智能体。
- [**Scout →**](https://github.com/agno-agi/scout) 一个管理企业上下文知识的自学习上下文智能体。
- [**Gcode →**](https://github.com/agno-agi/gcode) 一个能够随时间不断改进的后 IDE 阶段编程智能体。
- [**投资团队 →**](https://github.com/agno-agi/investment-team) 一个进行辩论并分配资金的多智能体投资委员会。

单个智能体、协作团队、结构化工作流。一切都构建在同一个架构之上。

## 开始使用

1. [阅读文档](https://docs.agno.com)
2. [构建您的第一个智能体](https://docs.agno.com/first-agent)
3. 探索 [Cookbook](https://github.com/agno-agi/agno/tree/main/cookbook)

## IDE 集成

将 Agno 文档添加为编程工具的源：

**Cursor:** Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`

同时也适用于 VSCode、Windsurf 及类似工具。

## 参与贡献

请参阅 [贡献指南](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md)。

## 遥测 (Telemetry)

Agno 会记录使用的模型提供商信息，以便优先更新。使用 `AGNO_TELEMETRY=false` 可禁用此功能。

<p align="right"><a href="#top">↑ 回到顶部</a></p>
