import asyncio
import logging
from time import sleep
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 2  # Exponential backoff: 1, 2, 4, 8...


def fetch_with_retry(
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: int = DEFAULT_BACKOFF_FACTOR,
) -> httpx.Response:
    """Synchronous HTTP GET with retry logic."""

    for attempt in range(max_retries):
        try:
            response = httpx.get(url)
            response.raise_for_status()
            return response
        except httpx.RequestError as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                raise
            wait_time = backoff_factor**attempt
            logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {wait_time} seconds...")
            sleep(wait_time)
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for {url}: {e.response.status_code} - {e.response.text}")
            raise

    raise httpx.RequestError(f"Failed to fetch {url} after {max_retries} attempts")


async def async_fetch_with_retry(
    url: str,
    client: Optional[httpx.AsyncClient] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: int = DEFAULT_BACKOFF_FACTOR,
) -> httpx.Response:
    """Asynchronous HTTP GET with retry logic."""

    async def _fetch():
        if client is None:
            async with httpx.AsyncClient() as local_client:
                return await local_client.get(url)
        else:
            return await client.get(url)

    for attempt in range(max_retries):
        try:
            response = await _fetch()
            response.raise_for_status()
            return response
        except httpx.RequestError as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                raise
            wait_time = backoff_factor**attempt
            logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {wait_time} seconds...")
            await asyncio.sleep(wait_time)
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for {url}: {e.response.status_code} - {e.response.text}")
            raise

    raise httpx.RequestError(f"Failed to fetch {url} after {max_retries} attempts")
