import json
import time
from encodings import search_function
from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, Table, Column, String, MetaData, select
from sqlalchemy.dialects.postgresql import insert
from agno.tools import Toolkit
from agno.utils.log import logger
from googlesearch import search
from pycountry import pycountry

class CachedSearchTools(Toolkit):
    def __init__(
        self,
        db_url: str,
        table_name: str,
        search_tool: Toolkit,
        fixed_max_results: Optional[int] = None,
        fixed_language: Optional[str] = None,
        sleep: Optional[float] = 0.1,
    ):

        super().__init__(name="cached_" + search_tool.name)
        
        self.search_tool = search_tool
        # Set up the database connection and table
        self.engine = create_engine(db_url)
        self.metadata = MetaData()
        self.table = Table(
            table_name,
            self.metadata,
            Column("query", String, primary_key=True),
            Column("results", String),
        )
        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language
        self.metadata.create_all(self.engine)
        self.sleep = sleep

        self.register(self.web_search)

    def getSearchFunction(self):
        # Assuming search_tool.functions is a dictionary of function names and their corresponding function objects
        #earch_function = next((func for func in self.search_tool.functions if "search" in func), None)
        search_function = next((self.search_tool.functions[func] for func in self.search_tool.functions if "search" in func), None)

        if search_function:
            print(f"Found function: {search_function}")
            return search_function
        else:
            print("No function containing 'search' found.")
            return None

    def web_search(self, query: str, max_results: int = 5, language: str = "en") -> str:
        max_results = self.fixed_max_results or max_results
        language = self.fixed_language or language

        # Resolve language to ISO 639-1 code if needed
        if len(language) != 2:
            _language = pycountry.languages.lookup(language)
            if _language:
                language = _language.alpha_2
            else:
                language = "en"

        logger.debug(f"Searching Google [{language}] for: {query}")

        # Check the cache first
        with self.engine.connect() as conn:
            stmt = select(self.table.c.results).where(self.table.c.query == query)
            result = conn.execute(stmt).fetchone()
            if result:
                logger.info(f"Cache hit for query: {query}")
                return result[0]  # Access the first element of the tuple


        time.sleep(self.sleep) # prevent rate limiting. Open for suggestions to handle this better.
        # Perform Google search using the googlesearch-python package

        search_function = self.getSearchFunction()
        results_json = search_function.entrypoint(query)

   # results_json = self.search_tool(query, max_results=max_results, language=language)

        # Store the results in the cache
        with self.engine.connect() as conn:
            stmt = insert(self.table).values(query=query, results=results_json).on_conflict_do_nothing()
            conn.execute(stmt)
            conn.commit()

        return results_json


