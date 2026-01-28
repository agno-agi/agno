#!/usr/bin/env python3
"""
开发模式启动脚本
启动一个基本的AgentOS服务器用于开发和测试
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.file import FileTools
from agno.tools.shell import ShellTools
from agno.db.sqlite import SqliteDb
import os

import openai

# 角色映射函数


def map_developer_role_to_assistant(messages):
    """将developer角色映射为assistant角色"""
    if not messages:
        return messages

    for msg in messages:
        if isinstance(msg, dict) and msg.get('role') == 'developer':
            msg['role'] = 'assistant'
    return messages


# 保存原始的create方法并应用补丁
try:
    # 尝试访问新版本的openai库结构
    if hasattr(openai, 'resources'):
        original_create = openai.resources.chat.completions.Completions.create  # type: ignore
        original_acreate = openai.resources.chat.completions.AsyncCompletions.create  # type: ignore

        def patched_create(self, **kwargs):
            if 'messages' in kwargs:
                kwargs['messages'] = map_developer_role_to_assistant(
                    kwargs['messages'])
            return original_create(self, **kwargs)

        async def patched_acreate(self, **kwargs):
            if 'messages' in kwargs:
                kwargs['messages'] = map_developer_role_to_assistant(
                    kwargs['messages'])
            return await original_acreate(self, **kwargs)

        # 应用猴子补丁
        openai.resources.chat.completions.Completions.create = patched_create  # type: ignore
        openai.resources.chat.completions.AsyncCompletions.create = patched_acreate  # type: ignore

except (AttributeError, ImportError):
    # 如果无法访问resources，跳过补丁
    print("⚠️  无法应用OpenAI角色映射补丁，将使用默认行为")


# 设置环境变量（如果需要的话）
os.environ["OPENAI_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
os.environ["OPENAI_API_KEY"] = "sk-2d32c23e21dc446e9dccea1fd9862cdc"

# 创建数据库
db = SqliteDb(db_file="tmp/dev_agno.db")

# 创建基本的开发Agent
dev_agent = Agent(
    name="开发助手",
    description="一个用于开发和测试的AI助手",
    model=OpenAIChat(id="qwen-plus"),  # 使用较便宜的模型进行开发
    tools=[
        DuckDuckGoTools(),  # 搜索工具
        FileTools(),        # 文件操作工具
        ShellTools(),       # Shell命令工具
    ],
    db=db,
    instructions=[
        "你是一个开发助手，可以帮助用户进行开发工作。",
        "你可以搜索信息、操作文件和执行shell命令。",
        "请始终以中文回复用户。",
        "在执行任何可能有风险的操作前，请先询问用户确认。"
    ],
    enable_session_summaries=True,
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
)

# 创建专业化的agents
research_agent = Agent(
    name="研究员",
    description="专门负责信息搜索和研究的AI助手",
    model=OpenAIChat(id="qwen-plus"),
    tools=[DuckDuckGoTools()],
    db=db,
    instructions=[
        "你是一个专业的研究员，擅长搜索和分析信息。",
        "你的任务是找到准确、相关的信息并进行初步分析。",
        "请提供详细的搜索结果和数据来源。",
        "始终以中文回复。"
    ],
    add_history_to_context=True,
    markdown=True,
)

code_agent = Agent(
    name="代码专家",
    description="专门负责代码相关任务的AI助手",
    model=OpenAIChat(id="qwen-plus"),
    tools=[FileTools(), ShellTools()],
    db=db,
    instructions=[
        "你是一个代码专家，擅长编写、分析和调试代码。",
        "你可以操作文件和执行shell命令来完成开发任务。",
        "请遵循最佳实践，编写清晰、可维护的代码。",
        "在执行可能有风险的操作前请先确认。",
        "始终以中文回复。"
    ],
    add_history_to_context=True,
    markdown=True,
)

# 创建开发团队
dev_team = Team(
    name="开发团队",
    description="一个协作的AI开发团队，包含研究员和代码专家",
    members=[research_agent, code_agent],
    model=OpenAIChat(id="qwen-plus"),
    instructions=[
        "你们是一个协作的开发团队。",
        "研究员负责信息搜索和分析，代码专家负责代码实现。",
        "请根据任务需要合理分工，确保高质量的输出。",
        "团队成员之间要有效沟通，避免重复工作。"
    ],
    db=db,
    add_history_to_context=True,
    markdown=True,
)

# 创建AgentOS应用
agent_os = AgentOS(
    description="Agno开发模式服务器",
    agents=[dev_agent],
    teams=[dev_team],
    # 可以添加更多配置
)

# 获取FastAPI应用
app = agent_os.get_app()

if __name__ == "__main__":
    print("🚀 启动Agno开发模式...")
    print("📝 配置信息:")
    print(f"   - 单独Agent: {dev_agent.name}")
    print(f"   - 开发团队: {dev_team.name}")
    print(
        f"     └── 成员: {', '.join([member.name for member in dev_team.members])}")
    print(f"   - 数据库: {db.db_file}")
    print(f"   - 工具: {len(dev_agent.tools) if dev_agent.tools else 0} 个")
    print("\n🌐 服务器将在以下地址启动:")
    print("   - 主页: http://localhost:7777")
    print("   - 配置: http://localhost:7777/config")
    print("   - API文档: http://localhost:7777/docs")
    print("\n💡 提示:")
    print("   - 按 Ctrl+C 停止服务器")
    print("   - 修改代码后服务器会自动重启")
    print("   - 查看日志了解运行状态")
    print("\n" + "="*50)

    # 启动服务器
    agent_os.serve(
        app="dev_server:app",
        host="0.0.0.0",
        port=7777,
        reload=True,  # 开发模式自动重载
        log_level="info"
    )
