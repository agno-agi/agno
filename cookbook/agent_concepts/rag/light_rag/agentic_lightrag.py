import os
import asyncio
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import gpt_4o_mini_complete, gpt_4o_complete, openai_embed
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.utils import setup_logger
from pathlib import Path


import textract



setup_logger("lightrag", level="INFO")

WORKING_DIR = "./rag_storage"
if not os.path.exists(WORKING_DIR):
    os.mkdir(WORKING_DIR)

async def initialize_rag():
    rag = LightRAG(
        working_dir=WORKING_DIR,
        embedding_func=openai_embed,
        llm_model_func=gpt_4o_complete,
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag

async def main():
    try:
        # Initialize RAG instance
        rag = await initialize_rag()
        print("RAG initialized")
       
       
        file_path = 'tmp/cv_1.pdf'
        with open(file_path, 'rb') as file:
            pdf_content = file.read()
            text_str = textract.process(file_path).decode('utf-8')
            print(file_path)
            await rag.ainsert(text_str)
        # text_content = textract.process(str(file_path))
        # await rag.ainsert(text_content)
        # # Perform hybrid search
        mode="hybrid"
        # mode="local"
        res = await rag.aquery(
              "What knowledge do have?",
              param=QueryParam(mode=mode)
          )
        print(res)

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if rag:
            await rag.finalize_storages()

if __name__ == "__main__":
    asyncio.run(main())