from agno.knowledge.agent import AgentKnowledge
from typing import Optional, Dict, Any, List, Union, Iterator
from lightrag import LightRAG, QueryParam
from pathlib import Path
from agno.vectordb.base import VectorDb
from lightrag.llm.openai import gpt_4o_mini_complete, gpt_4o_complete, openai_embed
from lightrag.kg.shared_storage import initialize_pipeline_status
from agno.document.reader.pdf_reader import PDFUrlImageReader, PDFUrlReader
from agno.document.reader.markdown_reader import MarkdownReader
from agno.document.reader.url_reader import URLReader

import textract
from agno.utils.log import log_info, log_debug,logger

class LightRagKnowledgeBase(AgentKnowledge):
    

    lightrag_server_url: str = "http://localhost:9621"
    path: Optional[Union[str, Path, List[Dict[str, Union[str, Dict[str, Any]]]]]] = None
    urls: Optional[Union[List[str], List[Dict[str, Union[str, Dict[str, Any]]]]]] = None
    reader: MarkdownReader = MarkdownReader()
    url_reader: URLReader = URLReader()


    @property
    def document_lists(self) -> Iterator[List[str]]:
        """Iterate over documents and yield lists of text content."""
        if self.path is not None:

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

                    
        elif self.urls is not None:
            log_info(f"Processing URLs: {self.urls}")
            for item in self.urls:
                if isinstance(item, dict) and "url" in item:
                    # Handle URL with metadata
                    url = item["url"]
                    config = item.get("metadata", {})
                    log_debug(f"Processing URL with metadata - URL: {url}, Config: {config}")
                    if self._is_valid_url(url):
                        log_debug(f"URL is valid, reading documents from: {url}")
                        documents = self.url_reader.read(url=url)
                        text_contents = []
                        for doc in documents:
                            if config:
                                log_debug(f"Adding metadata {config} to document from URL: {url}")
                                doc.meta_data.update(config)
                            # Extract text content from Document object
                            text_contents.append(doc.content)
                        yield text_contents
                else:
                    # Handle simple URL
                    log_debug(f"Processing simple URL: {item}")
                    if self._is_valid_url(item):
                        log_debug(f"Simple URL is valid, reading documents from: {item}")
                        documents = self.url_reader.read(url=item)
                        # Extract text content from Document objects
                        text_contents = [doc.content for doc in documents]
                        yield text_contents

        if self.urls is None and self.path is None:
            raise ValueError("Path or URLs are not set")

    async def load(self) -> None:
        logger.debug("Loading LightRagKnowledgeBase")
        for text_list in self.document_lists:
            for text in text_list:
                await self._insert_text(text)
        

    async def aload_document(
        self,
        path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load a single document from a file path or URL into the LightRAG server.
        
        Args:
            path: The file path or URL to load
            metadata: Optional metadata to associate with the document
            recreate: Ignored for LightRAG (kept for compatibility)
            upsert: Ignored for LightRAG (kept for compatibility) 
            skip_existing: Ignored for LightRAG (kept for compatibility)
        """
        try:
            # Determine if path is a URL or local file
            path_str = str(path)
            if path_str.startswith(("http://", "https://")):
                # Handle URL
                if not self._is_valid_url(path_str):
                    logger.error(f"Invalid URL format: {path_str}")
                    return
                    
                log_info(f"Loading document from URL: {path_str}")
                documents = self.url_reader.read(url=path_str)
            else:
                # Handle local file path
                _file_path = Path(path) if isinstance(path, str) else path
                
                if not _file_path.exists() or not _file_path.is_file():
                    logger.error(f"File does not exist: {_file_path}")
                    return
                    
                log_info(f"Loading document from file: {_file_path}")
                
                # Use textract for local files (consistent with document_lists method)
                try:
                    text_content = textract.process(str(_file_path)).decode('utf-8')
                    # Create a simple document-like structure for consistency
                    documents = [type('Document', (), {'content': text_content, 'meta_data': {}})()]
                except Exception as e:
                    logger.error(f"Failed to process file with textract: {e}")
                    return
            
            # Process each document
            for doc in documents:
                # Add metadata if provided
                if metadata and hasattr(doc, 'meta_data'):
                    doc.meta_data.update(metadata)
                    log_info(f"Added metadata {metadata} to document from: {path}")
                
                # Insert the document content into LightRAG server
                await self._insert_text(doc.content)
                
            log_info(f"Successfully loaded {len(documents)} document(s) from: {path}")
            
        except Exception as e:
            logger.exception(f"Failed to load document from {path}: {e}")
            return

    async def async_search(self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None):
        """Override the async_search method from AgentKnowledge to query the LightRAG server."""
        import httpx
        print(f"Querying LightRAG server with query: {query}")
        mode = "hybrid"  # Default mode, can be "local", "global", or "hybrid"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.lightrag_server_url}/query",
                json={"query": query, "mode": mode},
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            result = response.json()
            print(f"Query result: {result}")
            return result
    
    async def _insert_text(self, text: str):
        """Insert text into the LightRAG server."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.lightrag_server_url}/documents/text",
                json={"text": text},
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            print(response.json())
            return response.json()
        
    def _is_valid_url(self, url: str) -> bool:
        """Helper to check if URL is valid."""
        supported_extensions = [".pdf", ".md", ".txt"]
        if not any(url.endswith(ext) for ext in supported_extensions):
            logger.error(f"Unsupported URL: {url}. Supported file types: {', '.join(supported_extensions)}")
            return False
        return True
    

class LightRagRetriever():
    async def retriever(
        self,
        query: str,
        num_documents: int = 5,
        mode: str = "hybrid", # Default mode, can be "local", "global", or "hybrid"
        lightrag_server_url: str = "http://localhost:9621"
    ) -> Optional[list[dict]]:
        """
        Custom retriever function to search the LightRAG server for relevant documents.

        Args:
            query (str): The search query string
        Returns:
            Optional[list[dict]]: List of retrieved documents or None if search fails
        """
        try:
            import httpx
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{lightrag_server_url}/query",
                    json={"query": query, "mode": mode},
                    headers={"Content-Type": "application/json"}
                )
                
                response.raise_for_status()
                result = response.json()
                
                # LightRAG server returns a dict with 'response' key, but we expect a list of documents
                # Convert the response to the expected format
                if isinstance(result, dict) and 'response' in result:
                    # Wrap the response in a document-like structure
                    formatted_result = [{
                        "content": result['response'],
                        "source": "lightrag",
                        "metadata": {"query": query, "mode": mode}
                    }]
                    return formatted_result
                elif isinstance(result, list):
                    return result
                else:
                    # If it's a string or other format, wrap it
                    return [{
                        "content": str(result),
                        "source": "lightrag", 
                        "metadata": {"query": query, "mode": mode}
                    }]
                    
        except httpx.RequestError as e:
            logger.error(f"HTTP Request Error: {type(e).__name__}: {str(e)}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Status Error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during LightRAG server search: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return None
