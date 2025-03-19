import json
import time
from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, Table, Column, String, MetaData, select
from sqlalchemy.dialects.postgresql import insert
from agno.tools import Toolkit
from agno.utils.log import logger
from googlesearch import search
from pycountry import pycountry
from dotenv import load_dotenv
import os

load_dotenv()
language = os.getenv("LANG")
db_url = os.getenv("DB_URL")




class CachedGoogleSearchTools(Toolkit):
    def __init__(
        self,
        db_url: str,
        table_name: str,
        fixed_max_results: Optional[int] = None,
        fixed_language: Optional[str] = None,
        headers: Optional[Any] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 10,
    ):
        super().__init__(name="cached_googlesearch")
        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language
        self.headers = headers
        self.proxy = proxy
        self.timeout = timeout

        # Set up the database connection and table
        self.engine = create_engine(db_url)
        self.metadata = MetaData()
        self.table = Table(
            table_name,
            self.metadata,
            Column("query", String, primary_key=True),
            Column("results", String),
        )
        self.metadata.create_all(self.engine)

        self.register(self.google_search)

    def google_search(self, query: str, max_results: int = 5, language: str = "en") -> str:
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

        time.sleep(0.2) # prevent rate limiting. Open for suggestions to handle this better.
        # Perform Google search using the googlesearch-python package
        results = list(search(query, num_results=max_results, lang=language, proxy=self.proxy, advanced=True))

        # Collect the search results
        res: List[Dict[str, str]] = []
        for result in results:
            res.append(
                {
                    "title": result.title,
                    "url": result.url,
                    "description": result.description,
                }
            )

        results_json = json.dumps(res, indent=2)

        # Store the results in the cache
        with self.engine.connect() as conn:
            stmt = insert(self.table).values(query=query, results=results_json).on_conflict_do_nothing()
            conn.execute(stmt)
            conn.commit()

        return results_json

class CachedGoogleSearchToolsFactory(object):
    load_dotenv()
    language = os.getenv("LANG")
    db_url = os.getenv("DB_URL")

    cached_search_tool = CachedGoogleSearchTools(
        db_url=db_url,
        table_name="search_cache",
        fixed_max_results=10,
        fixed_language=language
    )

    def get_search_tool(self) -> CachedGoogleSearchTools:
        return self.cached_search_tool
