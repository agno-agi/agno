from agno.agent import Agent
from agno.knowledge.combined import CombinedKnowledgeBase
from agno.knowledge.csv import CSVKnowledgeBase
from agno.knowledge.docx import DocxKnowledgeBase
from agno.knowledge.json import JSONKnowledgeBase
from agno.knowledge.pdf import PDFKnowledgeBase
from agno.knowledge.text import TextKnowledgeBase
from agno.playground.playground import Playground
from agno.playground.serve import serve_playground_app
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = CombinedKnowledgeBase(
    sources=[
        PDFKnowledgeBase(
            vector_db=PgVector(table_name="recipes_pdf", db_url=db_url), path=""
        ),
        CSVKnowledgeBase(
            vector_db=PgVector(table_name="recipes_csv", db_url=db_url), path=""
        ),
        DocxKnowledgeBase(
            vector_db=PgVector(table_name="recipes_docx", db_url=db_url), path=""
        ),
        JSONKnowledgeBase(
            vector_db=PgVector(table_name="recipes_json", db_url=db_url), path=""
        ),
        TextKnowledgeBase(
            vector_db=PgVector(table_name="recipes_text", db_url=db_url), path=""
        ),
    ],
    vector_db=PgVector(table_name="recipes_combined", db_url=db_url),
)

agent = Agent(knowledge=knowledge_base, show_tool_calls=True)

app = Playground(agents=[agent]).get_app()

if __name__ == "__main__":
    serve_playground_app("upload_files:app", reload=True)
