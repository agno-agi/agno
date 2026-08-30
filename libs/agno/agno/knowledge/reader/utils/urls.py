"""URL canonicalization for page-level knowledge rows.

Kept free of heavy imports: ``knowledge.py`` uses it on the per-page insert path,
which must not require the html-parsing extras.
"""

import hashlib
from urllib.parse import unquote, urlparse

# Contents-db row names must fit the narrowest adapter column (MySQL: String(255)).
MAX_PAGE_NAME_LENGTH = 255

_INDEX_SUFFIXES = ("index.html", "index.htm")


def canonical_page_name(url: str) -> str:
    """A stable, human-readable name for one page: ``<host>/<path>``.

    Two sitemap entries for the same page must produce the same name, so the fragment is
    dropped, a trailing slash and a trailing ``index.html``/``index.htm`` are stripped, and
    the path is percent-decoded. The query is kept when present — ``?v=1`` and ``?v=2`` are
    different pages. The site root is just the host. Names longer than the narrowest
    contents-db column are truncated with a short hash suffix so they stay unique.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path or "")

    for suffix in _INDEX_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    path = path.strip("/")

    name = f"{host}/{path}" if path else host
    if parsed.query:
        name = f"{name}?{parsed.query}"

    if len(name) > MAX_PAGE_NAME_LENGTH:
        digest = hashlib.sha256(name.encode()).hexdigest()[:8]
        name = f"{name[: MAX_PAGE_NAME_LENGTH - 9]}-{digest}"
    return name


def is_sitemap_url(url: str) -> bool:
    """Whether a URL names a sitemap file (``sitemap*.xml`` / ``sitemap*.xml.gz``)."""
    path = urlparse(url).path.lower()
    segment = path.rsplit("/", 1)[-1]
    return segment.startswith("sitemap") and (segment.endswith(".xml") or segment.endswith(".xml.gz"))


def canonical_page_url(url: str) -> str:
    """The canonical form of a page URL for identity and de-duplication.

    Same rules as :func:`canonical_page_name` applied to the URL itself: fragment dropped,
    trailing slash and ``index.html``/``index.htm`` stripped, query kept. The scheme and host
    are lowercased; the path keeps its original encoding (it is what gets fetched).
    """
    parsed = urlparse(url)
    path = parsed.path or ""
    for suffix in _INDEX_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    # The site root's two spellings ("" and "/") must canonicalise identically
    path = path.rstrip("/")

    scheme = (parsed.scheme or "https").lower()
    host = (parsed.netloc or "").lower()
    canonical = f"{scheme}://{host}{path}"
    if parsed.query:
        canonical = f"{canonical}?{parsed.query}"
    return canonical
