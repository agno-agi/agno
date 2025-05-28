from agno.knowledge.agent import AgentKnowledge
from typing import Optional, Dict, Any, List, Union, Iterator
from lightrag import LightRAG, QueryParam
from pathlib import Path
from agno.vectordb.base import VectorDb
from lightrag.llm.openai import gpt_4o_mini_complete, gpt_4o_complete, openai_embed
from lightrag.kg.shared_storage import initialize_pipeline_status

import os
import textract

class LightRagKnowledgeBase(AgentKnowledge):

    rag: LightRAG
    path: Optional[Union[str, Path, List[Dict[str, Union[str, Dict[str, Any]]]]]] = None

    @property
    def document_lists(self) -> Iterator[List[str]]:
        """Iterate over documents and yield lists of text content."""
        if self.path is None:
            raise ValueError("Path is not set")

        if isinstance(self.path, list):
            for item in self.path:
                if isinstance(item, dict) and "path" in item:
                    # Handle path with metadata
                    file_path = item["path"]
                    _path = Path(file_path)
                    if _path.exists() and _path.is_file():
                        text_str = textract.process(str(_path)).decode('utf-8')
                        yield [text_str]
        else:
            # Handle single path
            _path = Path(self.path)
            if _path.is_dir():
                for file_path in _path.glob("**/*"):
                    if file_path.is_file():
                        text_str = textract.process(str(file_path)).decode('utf-8')
                        yield [text_str]
            elif _path.exists() and _path.is_file():
                text_str = textract.process(str(_path)).decode('utf-8')
                yield [text_str]

    @classmethod
    async def create(
        cls,
        path: Optional[Union[str, Path, List[Dict[str, Union[str, Dict[str, Any]]]]]] = None,
        vector_db: Optional[VectorDb] = None,
    ) -> "LightRagKnowledgeBase":
        
        WORKING_DIR = "./rag_storage"
        if not os.path.exists(WORKING_DIR):
            os.mkdir(WORKING_DIR)

        rag = LightRAG(
            working_dir=WORKING_DIR,
            embedding_func=openai_embed,
            llm_model_func=gpt_4o_complete,
        )
        await rag.initialize_storages()
        await initialize_pipeline_status()

        return cls(rag=rag, path=path)
    
    async def load(self, recreate: bool = False, upsert: bool = False, skip_existing: bool = True) -> None:
        print("Loading LightRagKnowledgeBase")
        if self.path:
            for text_list in self.document_lists:
                for text in text_list:
                    await self.rag.ainsert(text)

    async def aload(self, recreate: bool = False, upsert: bool = False, skip_existing: bool = True) -> None:
        pass

    async def search(self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None):
        mode="hybrid"
        # mode="local"
        res = await self.rag.aquery(
              query,
              param=QueryParam(mode=mode)
          )
        return res