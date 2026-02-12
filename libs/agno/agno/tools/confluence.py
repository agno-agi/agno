import re
from difflib import SequenceMatcher
import unicodedata
from os import getenv
from typing import Any, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

try:
    from atlassian import Confluence
except (ModuleNotFoundError, ImportError):
    raise ImportError("atlassian-python-api not install . Please install using `pip install atlassian-python-api`")


class ConfluenceTools(Toolkit):
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        verify_ssl: bool = True,
        **kwargs,
    ):
        """Initialize Confluence Tools with authentication credentials.

        Args:
            username (str, optional): Confluence username. Defaults to None.
            password (str, optional): Confluence password. Defaults to None.
            url (str, optional): Confluence instance URL. Defaults to None.
            api_key (str, optional): Confluence API key. Defaults to None.
            verify_ssl (bool, optional): Whether to verify SSL certificates. Defaults to True.

        Notes:
            Credentials can be provided either through method arguments or environment variables:
            - CONFLUENCE_URL
            - CONFLUENCE_USERNAME
            - CONFLUENCE_API_KEY
        """

        self.url = url or getenv("CONFLUENCE_URL")
        self.username = username or getenv("CONFLUENCE_USERNAME")
        self.password = api_key or getenv("CONFLUENCE_API_KEY") or password or getenv("CONFLUENCE_PASSWORD")

        if not self.url:
            raise ValueError(
                "Confluence URL not provided. Pass it in the constructor or set CONFLUENCE_URL in environment variable"
            )

        if not self.username:
            raise ValueError(
                "Confluence username not provided. Pass it in the constructor or set CONFLUENCE_USERNAME in environment variable"
            )

        if not self.password:
            raise ValueError("Confluence API KEY or password not provided")

        session = requests.Session()
        session.verify = verify_ssl

        if not verify_ssl:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.confluence = Confluence(
            url=self.url,
            username=self.username,
            password=self.password,
            verify_ssl=verify_ssl,
            session=session,
        )

        tools: List[Any] = [
            self.get_page_content,
            self.getpagecontent,
            self.get_space_key,
            self.find_page_by_partial_title,
            self.get_page_by_slug,
            self.getpagebyslug,
            self.create_page,
            self.update_page,
            self.get_all_space_detail,
            self.get_all_page_from_space,
        ]

        super().__init__(name="confluence_tools", tools=tools, **kwargs)

    @staticmethod
    def _slugify_title(title: str) -> str:
        """Convert a page title into the slug used in Confluence URLs (spaces/specials to '+')."""
        normalized = unicodedata.normalize("NFKD", title or "")
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        slug_chars: List[str] = []
        for ch in normalized:
            if re.match(r"[A-Za-z0-9-]", ch):
                slug_chars.append(ch.lower())
            else:
                slug_chars.append("+")
        slug = "".join(slug_chars)
        slug = re.sub(r"\++", "+", slug).strip("+")
        return slug

    @staticmethod
    def _normalize_key(text: str) -> str:
        """Normalize a title for fuzzy matching: lower, strip accents, alnum+spaces."""
        normalized = unicodedata.normalize("NFKD", text or "")
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower())
        return " ".join(normalized.split())

    @staticmethod
    def _token_overlap(query_norm: str, page_norm: str) -> bool:
        """Check if all significant query tokens appear (prefix/equals) in page tokens."""
        stop = {"de", "da", "do", "das", "dos", "em", "e", "a", "o", "para", "the", "and", "or", "of"}
        q_tokens = [t for t in (query_norm or "").split() if len(t) > 2 and t not in stop]
        if not q_tokens:
            return False
        p_tokens = (page_norm or "").split()

        # Count how many query tokens are found in page tokens
        matched_count = 0
        for qt in q_tokens:
            for pt in p_tokens:
                if qt == pt or pt.startswith(qt) or qt.startswith(pt) or SequenceMatcher(None, qt, pt).ratio() >= 0.85:
                    matched_count += 1
                    break

        # Return True if at least 70% of query tokens are found
        return matched_count >= len(q_tokens) * 0.7

    def _find_page_by_normalized(self, space_key: str, query_title: str) -> Optional[dict]:
        """Try to locate a page by normalized/slugged title within a space."""
        pages: List[dict] = []
        start = 0
        limit = 200
        try:
            while True:
                batch = self.confluence.get_all_pages_from_space(
                    space_key, start=start, limit=limit, status=None, expand=None, content_type="page"
                )
                if not batch:
                    break
                pages.extend(batch)
                if len(batch) < limit:
                    break
                start += limit
        except Exception as exc:
            logger.error(f"Error listing pages in space '{space_key}': {exc}")
            return None

        if not pages:
            return None

        query_slug = self._slugify_title(query_title)
        query_norm = self._normalize_key(query_title)

        exact_slug = None
        exact_norm = None
        partial_matches: List[tuple[dict, float]] = []  # (page, score)

        for page in pages:
            title = page.get("title", "")
            page_slug = self._slugify_title(title)
            page_norm = self._normalize_key(title)

            # Exact matches have highest priority
            if page_slug == query_slug:
                exact_slug = page
                break
            if page_norm == query_norm:
                exact_norm = page

            # Calculate match score for partial matches
            score = 0.0

            # Substring match in slug (high score)
            if query_slug and query_slug in page_slug:
                score += 0.8

            # Substring match in normalized text
            if query_norm and query_norm in page_norm:
                score += 0.7

            # Token overlap (medium score)
            if query_norm and self._token_overlap(query_norm, page_norm):
                score += 0.6

            # Sequence matcher similarity
            if query_norm and page_norm:
                similarity = SequenceMatcher(None, query_norm, page_norm).ratio()
                if similarity > 0.5:
                    score += similarity * 0.5

            if score > 0:
                partial_matches.append((page, score))

        if exact_slug:
            return exact_slug
        if exact_norm:
            return exact_norm

        # Sort partial matches by score (highest first)
        if partial_matches:
            partial_matches.sort(key=lambda x: x[1], reverse=True)
            return partial_matches[0][0]

        # Fallback: CQL search inside the space
        try:
            cql = f'type=page AND space="{space_key}" AND text~"{query_title}"'
            results = self.confluence.cql(cql, limit=5, start=0).get("results", [])
            for res in results:
                content = res.get("content", {})
                return {
                    "id": content.get("id"),
                    "title": content.get("title"),
                }
        except Exception as exc:
            logger.warning(f"CQL search failed in space '{space_key}' for '{query_title}': {exc}")

        return None

    @staticmethod
    def _summarize_html(html: str, max_chars: int = 800) -> str:
        """Crude summary: strip tags and truncate."""
        text = re.sub(r"<[^>]+>", " ", html or "")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            return text[: max_chars - 3] + "..."
        return text

    def get_page_content(self, space_name: str, page_title: str, expand: Optional[str] = "body.storage"):
        """Retrieve the content of a specific page in a Confluence space.

        Args:
            space_name (str): Name of the Confluence space.
            page_title (str): Title of the page to retrieve.
            expand (str, optional): Fields to expand in the page response. Defaults to "body.storage".

        Returns:
            str: User-friendly page content or error message.
        """
        try:
            log_info(f"Retrieving page content from space '{space_name}'")
            key = self.get_space_key(space_name=space_name)
            if key == "No space found":
                return f"Space '{space_name}' not found."

            # Normalize spoken title to slug and fuzzy-match within the space before fetching
            matched_page = self._find_page_by_normalized(key, page_title)
            if matched_page:
                page_id = matched_page.get("id")
                page_title = matched_page.get("title", page_title)
                try:
                    page = self.confluence.get_page_by_id(page_id, expand=expand)
                except Exception:
                    page = self.confluence.get_page_by_title(key, page_title, expand=expand)
            else:
                # Fallback to exact title lookup
                page = self.confluence.get_page_by_title(key, page_title, expand=expand)

            if page:
                log_info(f"Successfully retrieved page '{page_title}' from space '{space_name}'")
                title = page.get("title", "Unknown")
                url = f"{self.url}/pages/viewpage.action?pageId={page.get('id', '')}"

                # Get summary
                summary = ""
                try:
                    html = page.get("body", {}).get("storage", {}).get("value", "")
                    summary = self._summarize_html(html)
                except Exception:
                    summary = "Content preview not available."

                result = f"Found page: {title}\n"
                result += f"URL: {url}\n\n"
                result += f"Content preview:\n{summary}"
                return result

            logger.warning(f"Page '{page_title}' not found in space '{space_name}'")
            return f"Page '{page_title}' not found in space '{space_name}'."

        except Exception as e:
            logger.error(f"Error retrieving page '{page_title}': {e}")
            return f"Error retrieving page: {str(e)}"

    # Aliases to be resilient to model tool-name formatting
    def getpagecontent(self, spacename: Optional[str] = None, pagetitle: Optional[str] = None, expand: str = "body.storage") -> str:
        return self.get_page_content(space_name=spacename or "", page_title=pagetitle or "", expand=expand)

    def get_all_space_detail(self):
        """Retrieve details about all Confluence spaces.

        Returns:
            str: List of space details as a string.
        """
        log_info("Retrieving details for all Confluence spaces")
        results = []
        start = 0
        limit = 50

        while True:
            spaces_data = self.confluence.get_all_spaces(start=start, limit=limit)
            if not spaces_data.get("results"):
                break
            results.extend(spaces_data["results"])

            if len(spaces_data["results"]) < limit:
                break
            start += limit

        return str(results)

    def get_space_key(self, space_name: str):
        """Get the space key for a particular Confluence space.

        Args:
            space_name (str): Name of the space whose key is required.

        Returns:
            str: Space key or "No space found" if space doesn't exist.
        """
        start = 0
        limit = 50

        while True:
            result = self.confluence.get_all_spaces(start=start, limit=limit)
            if not result.get("results"):
                break

            spaces = result["results"]

            for space in spaces:
                if space["name"].lower() == space_name.lower():
                    log_info(f"Found space key for '{space_name}': {space['key']}")
                    return space["key"]

            for space in spaces:
                if space["key"] == space_name:
                    log_info(f"'{space_name}' is already a space key")
                    return space_name

            if len(spaces) < limit:
                break
            start += limit

        logger.warning(f"No space named {space_name} found")
        return "No space found"

    def get_all_page_from_space(self, space_name: str):
        """Retrieve all pages from a specific Confluence space.

        Args:
            space_name (str): Name of the Confluence space.

        Returns:
            str: User-friendly list of pages in the specified space.
        """
        log_info(f"Retrieving all pages from space '{space_name}'")
        space_key = self.get_space_key(space_name)

        if space_key == "No space found":
            return f"Space '{space_name}' not found."

        page_details = self.confluence.get_all_pages_from_space(
            space_key, status=None, expand=None, content_type="page"
        )

        if not page_details:
            return f"No pages found in space '{space_name}'."

        result = f"Pages in space '{space_name}':\n"
        for i, page in enumerate(page_details, 1):
            title = page.get("title", "Unknown")
            result += f"{i}. {title}\n"

        return result

    def find_page_by_partial_title(self, space_name: str, partial_title: str, limit: int = 5) -> str:
        """Find pages in a space by partial/normalized title match and return top results."""
        log_info(f"Searching pages in space '{space_name}' by partial title '{partial_title}'")
        space_key = self.get_space_key(space_name)
        if space_key == "No space found":
            return f"Space '{space_name}' not found."

        matches: List[tuple[dict, float]] = []  # (page_info, score)
        pages: List[dict] = []
        start = 0
        page_limit = 200
        try:
            while True:
                batch = self.confluence.get_all_pages_from_space(
                    space_key, start=start, limit=page_limit, status=None, expand=None, content_type="page"
                )
                if not batch:
                    break
                pages.extend(batch)
                if len(batch) < page_limit:
                    break
                start += page_limit
        except Exception as exc:
            logger.error(f"Error listing pages in space '{space_name}': {exc}")
            return f"Error listing pages: {str(exc)}"

        query_slug = self._slugify_title(partial_title)
        query_norm = self._normalize_key(partial_title)

        for page in pages or []:
            title = page.get("title", "")
            page_slug = self._slugify_title(title)
            page_norm = self._normalize_key(title)

            # Calculate match score
            score = 0.0

            # Exact match (highest priority)
            if query_slug == page_slug or query_norm == page_norm:
                score += 2.0

            # Substring match in slug
            if query_slug and query_slug in page_slug:
                score += 0.8

            # Substring match in normalized text
            if query_norm and query_norm in page_norm:
                score += 0.7

            # Token overlap
            if query_norm and self._token_overlap(query_norm, page_norm):
                score += 0.6

            # Sequence similarity
            if query_norm and page_norm:
                similarity = SequenceMatcher(None, query_norm, page_norm).ratio()
                if similarity > 0.5:
                    score += similarity * 0.5

            if score > 0:
                matches.append(({"id": page.get("id"), "title": title}, score))

        if not matches:
            return f"No pages found matching '{partial_title}' in space '{space_name}'."

        # Sort by score (highest first) and take top results
        matches.sort(key=lambda x: x[1], reverse=True)
        top_matches = [match[0] for match in matches[:limit]]

        # Format matches as simple list (no URLs for voice readability)
        result = f"Found {len(top_matches)} page(s) matching '{partial_title}':\n"
        for i, match in enumerate(top_matches, 1):
            title = match.get("title", "Unknown")
            result += f"{i}. {title}\n"

        return result

    def get_page_by_slug(
        self,
        space_name: Optional[str] = None,
        page_slug: Optional[str] = None,
        slug: Optional[str] = None,
        spaceKey: Optional[str] = None,
        spacekey: Optional[str] = None,
        space: Optional[str] = None,
        pageslug: Optional[str] = None,
        expand: Optional[str] = "body.storage",
    ) -> str:
        """Retrieve a page by slug/normalized title within a space."""
        # Accept multiple param names to be resilient to model calls
        space_name = space_name or spaceKey or spacekey or space
        page_slug = page_slug or pageslug or slug

        if not space_name:
            return "Error: space_name is required."
        if not page_slug:
            return "Error: page_slug is required."

        log_info(f"Retrieving page by slug in space '{space_name}'")
        space_key = self.get_space_key(space_name)
        if space_key == "No space found":
            return f"Space '{space_name}' not found."

        matched_page = self._find_page_by_normalized(space_key, page_slug)
        if not matched_page:
            return f"Page matching '{page_slug}' not found in space '{space_name}'."

        page_id = matched_page.get("id")
        title = matched_page.get("title")
        try:
            page = self.confluence.get_page_by_id(page_id, expand=expand)
        except Exception as exc:
            logger.error(f"Error retrieving page by id '{page_id}': {exc}")
            return f"Error retrieving page: {str(exc)}"

        summary = ""
        try:
            html = page.get("body", {}).get("storage", {}).get("value", "")
            summary = self._summarize_html(html)
        except Exception:
            summary = "Content preview not available."

        url = f"{self.url}/pages/viewpage.action?pageId={page_id}"
        result = f"Found page: {title}\n"
        result += f"URL: {url}\n\n"
        result += f"Content preview:\n{summary}"
        return result

    # Alias for resilient tool-name matching
    def getpagebyslug(self, **kwargs) -> str:
        return self.get_page_by_slug(**kwargs)

    def create_page(self, space_name: str, title: str, body: str, parent_id: Optional[str] = None) -> str:
        """Create a new page in Confluence.

        Args:
            space_name (str): Name of the Confluence space.
            title (str): Title of the new page.
            body (str): Content of the new page.
            parent_id (str, optional): ID of the parent page if creating a child page. Defaults to None.

        Returns:
            str: User-friendly confirmation message or error.
        """
        try:
            space_key = self.get_space_key(space_name=space_name)
            if space_key == "No space found":
                return f"Space '{space_name}' not found."

            page = self.confluence.create_page(space_key, title, body, parent_id=parent_id)
            log_info(f"Page created: {title} with ID {page['id']}")

            page_id = page.get("id", "")
            url = f"{self.url}/pages/viewpage.action?pageId={page_id}"

            result = f"Page created successfully!\n"
            result += f"Title: {title}\n"
            result += f"URL: {url}"
            return result
        except Exception as e:
            logger.error(f"Error creating page '{title}': {e}")
            return f"Error creating page: {str(e)}"

    def update_page(self, page_id: str, title: str, body: str) -> str:
        """Update an existing Confluence page.

        Args:
            page_id (str): ID of the page to update.
            title (str): New title for the page.
            body (str): Updated content for the page.

        Returns:
            str: User-friendly confirmation message or error.
        """
        try:
            updated_page = self.confluence.update_page(page_id, title, body)
            log_info(f"Page updated: {title} with ID {updated_page['id']}")

            url = f"{self.url}/pages/viewpage.action?pageId={page_id}"

            result = f"Page updated successfully!\n"
            result += f"Title: {title}\n"
            result += f"URL: {url}"
            return result
        except Exception as e:
            logger.error(f"Error updating page '{title}': {e}")
            return f"Error updating page: {str(e)}"
