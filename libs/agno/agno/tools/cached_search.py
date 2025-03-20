import json
import time
from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, Table, Column, String, MetaData, select
from sqlalchemy.dialects.postgresql import insert
from agno.tools import Toolkit
from agno.utils.log import logger
from googlesearch import search
from pycountry import pycountry
from agno.tools.function import Function

class CachedSearchTools(Toolkit):
    def __init__(
        self,
        db_url: str,
        table_name: str,
        search_function: Function,
        fixed_max_results: Optional[int] = None,
        fixed_language: Optional[str] = None,
        sleep: Optional[float] = 0.1,
    ):

        #super().__init__(name="cached_search_" + search_function.name)
        super().__init__(name="cached_web_search")

        self.search_function = search_function
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
        results_json = self.search_function(query, max_results=max_results, language=language)

        # Store the results in the cache
        with self.engine.connect() as conn:
            stmt = insert(self.table).values(query=query, results=results_json).on_conflict_do_nothing()
            conn.execute(stmt)
            conn.commit()

        return results_json


