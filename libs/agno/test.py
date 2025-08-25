# """Multi-tool integration test: Comprehensive AI & Technology Research Agent

# This agent demonstrates the coordination of 8 different tools to complete a complex research task:
# 1. DuckDuckGo - Current news and market information
# 2. Wikipedia - Company background and industry context  
# 3. YFinance - Stock data and financial metrics
# 4. Calculator - Financial calculations and analysis
# 5. File - Save research findings to reports
# 6. ArXiv - Academic research papers and studies
# 7. Python - Data analysis and visualization code
# 8. Shell - System operations and environment setup

# Run `pip install duckduckgo-search yfinance wikipedia arxiv pypdf` to install dependencies.
# """
# import asyncio
# from agno.agent import Agent
# from agno.models.openai import OpenAIChat
# from agno.tools.arxiv import ArxivTools
# from agno.tools.calculator import CalculatorTools
# from agno.tools.duckduckgo import DuckDuckGoTools
# from agno.tools.file import FileTools
# from agno.tools.python import PythonTools
# from agno.tools.shell import ShellTools
# from agno.tools.wikipedia import WikipediaTools
# from agno.tools.yfinance import YFinanceTools

# # Create agent with 8 complementary tools for comprehensive research
# agent = Agent(
#     model=OpenAIChat(id="gpt-4o"),
#     tools=[
#         DuckDuckGoTools(),                    # 1. Web search for current information
#         WikipediaTools(),                     # 2. Knowledge base for background info
#         YFinanceTools(                        # 3. Financial data and stock analysis
#             stock_price=True,
#             company_info=True, 
#             analyst_recommendations=True,
#             company_news=True,
#             historical_prices=True
#         ),
#         CalculatorTools(enable_all=True),     # 4. Mathematical calculations
#         FileTools(                            # 5. File operations for reports
#             save_files=True, 
#             read_files=True,
#             list_files=True
#         ),
#         ArxivTools(                           # 6. Academic research papers
#             search_arxiv=True,
#             read_arxiv_papers=True
#         ),
#         PythonTools(                          # 7. Code execution and data analysis
#             save_and_run=True,
#             run_code=True,
#             list_files=True
#         ),
#         ShellTools()                          # 8. System commands and environment
#     ],
#     show_tool_calls=True,
#     markdown=True,
#     debug_mode=True,
# )

# # Advanced multi-tool research task requiring coordination of all 8 tools
# task = """
# Please conduct a comprehensive AI technology and market analysis focusing on NVIDIA and the AI/ML industry. Your research should leverage ALL available tools systematically:

# **Phase 1: Current Market Intelligence** 🌐
# 1. Search for the latest news about NVIDIA, AI chip market trends, and recent developments in generative AI
# 2. Get current stock price, analyst recommendations, and recent financial news for NVDA

# **Phase 2: Academic Research Foundation** 📚  
# 3. Get detailed background on NVIDIA from Wikipedia (history, business segments, competitive position)
# 4. Search ArXiv for recent academic papers on AI hardware, GPU computing, or neural network acceleration (limit to 3-5 most relevant)

# **Phase 3: Financial Analysis & Modeling** 💰
# 5. Retrieve comprehensive financial data: stock metrics, historical prices, company fundamentals
# 6. Calculate key financial ratios and projections:
#    - PE ratio analysis at different multiples (15x, 20x, 25x, 30x)
#    - Price performance over 30, 90, and 365 days
#    - Revenue growth rates if available

# **Phase 4: Technical Analysis & Code** 🐍
# 7. Write Python code to:
#    - Analyze NVIDIA's stock price trends
#    - Calculate moving averages and basic statistics
#    - Generate summary statistics of financial data
# 8. Save and execute the analysis code

# **Phase 5: Environment & System Analysis** ⚙️
# 9. Use shell commands to check system environment and create organized workspace
# 10. List and manage all generated files and reports

# **Phase 6: Comprehensive Documentation** 📄
# 11. Create a detailed research report saved as 'nvidia_comprehensive_analysis.md' that includes:
#     - Executive summary with key findings
#     - Market position and competitive analysis  
#     - Financial performance and projections
#     - Academic research insights
#     - Technical analysis results
#     - Investment thesis and risk factors

# **Coordination Requirements:**
# - Use information from previous tools to inform subsequent analysis
# - Cross-reference findings between different data sources
# - Ensure all 8 tools are utilized strategically
# - Build upon previous discoveries to create cohesive analysis

# Please work through this systematically, explaining your tool selection strategy and how each contributes to the overall analysis.
# """

# print("🚀 Starting Comprehensive Multi-Tool AI Technology Research...")
# print("📊 Utilizing 8 specialized tools for deep analysis...")
# print("=" * 80)

# asyncio.run(agent.aprint_response(task, stream=True))


from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.pdf import PDFKnowledgeBase
from agno.knowledge.markdown import MarkdownKnowledgeBase
from agno.document.reader.pdf_reader import PDFReader
from agno.models.openai.like import OpenAILike
from agno.document.chunking.document import DocumentChunking
from agno.vectordb.qdrant import Qdrant
import asyncio
from agno.models.openai import OpenAIChat
from dotenv import load_dotenv

load_dotenv()

COLLECTION_NAME = "duke_sc"
emdbedder = OpenAIEmbedder(
    id="Qwen/Qwen3-Embedding-8B",
    base_url="http://xxxx:3300/v1",
    api_key="secret",
    dimensions=4096,
)
vector_db = Qdrant(
    collection=COLLECTION_NAME,
    path=r"C:\Users",
    recreate=True,
    # location=":memory:",
    embedder=emdbedder,
)

knowledge_base = MarkdownKnowledgeBase(
    path=rf"C:\Users\Hxtreme\Documents\agno\agno\DukeFilledForm.md",
    vector_db=vector_db,
    chunking_strategy=DocumentChunking(),
    # reader=PDFReader(chunk=True),
)

# Create an agent with the knowledge base
model = OpenAIChat(
    id="gpt-5",
    reasoning_effort="high",
)
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    model=model,
    description="You are a helpful Agent called 'Interconnection Request Analysis RAG' and your goal is to assist the user in the best way possible.",
    instructions=[
        "1. Knowledge Base Search:",
        "   - ALWAYS start by searching the knowledge base using search_knowledge_base tool",
        "   - Analyze ALL returned documents thoroughly before responding",
        "   - If multiple documents are returned, synthesize the information coherently",
        "2. External Search:",
        "   - If knowledge base search yields insufficient results, use duckduckgo_search",
        "   - Focus on reputable sources and recent information",
        "   - Cross-reference information from multiple sources when possible",
        "3. Context Management:",
        "   - Use get_chat_history tool to maintain conversation continuity",
        "   - Reference previous interactions when relevant",
        "   - Keep track of user preferences and prior clarifications",
        "4. Response Quality:",
        "   - Provide specific citations and sources for claims",
        "   - Structure responses with clear sections and bullet points when appropriate",
        "   - Include relevant quotes from source materials",
        "   - Avoid hedging phrases like 'based on my knowledge' or 'depending on the information'",
        "5. User Interaction:",
        "   - Ask for clarification if the query is ambiguous",
        "   - Break down complex questions into manageable parts",
        "   - Proactively suggest related topics or follow-up questions",
        "6. Error Handling:",
        "   - If no relevant information is found, clearly state this",
        "   - Suggest alternative approaches or questions",
        "   - Be transparent about limitations in available information",
    ],
    markdown=True,
)


agent.print_response(
    "Share me any details regarding the generating facility information ",
    # markdown=True,
)