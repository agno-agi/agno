"""Public, same-origin single-page transport with bounded work.

DNS answers are pinned to the connection while the Host header and TLS server
name retain the original hostname, as in the documentation page fetcher.
"""

import asyncio
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Tuple
from urllib.parse import urljoin, urlsplit

import httpx

_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="public-page-dns")


async def _resolve(host: str, port: int):
    # Cancellation must not wait for the event loop's default DNS executor to shut down.
    return await asyncio.get_running_loop().run_in_executor(
        _DNS_POOL, lambda: socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    )


def public_url(url: str):
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in (None, 80 if parts.scheme == "http" else 443)
    ):
        raise ValueError("Website Sources require a public HTTP(S) URL on a standard port")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Website Sources cannot read private network addresses")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return parts
    if not address.is_global:
        raise ValueError("Website Sources cannot read private network addresses")
    return parts


async def _fetch(url: str, max_bytes: int) -> Tuple[str, bytes]:
    origin = public_url(url)
    current = url
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=10) as client:
        for _ in range(4):
            parts = public_url(current)
            if (parts.scheme, parts.hostname, parts.port) != (origin.scheme, origin.hostname, origin.port):
                raise ValueError("Website Source redirects must stay on the configured origin")
            addresses = await _resolve(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
            ips = [str(item[4][0]) for item in addresses]
            if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise ValueError("Website Sources cannot read private network addresses")
            # Never resolve the hostname a second time when establishing the connection.
            address = ips[0]
            authority = "[" + address + "]" if ":" in address else address
            pinned = parts._replace(netloc=authority, fragment="").geturl()
            async with client.stream(
                "GET",
                pinned,
                headers={"Host": parts.netloc, "Accept-Encoding": "identity"},
                extensions={"sni_hostname": parts.hostname},
            ) as response:
                if response.is_redirect:
                    current = urljoin(current, response.headers["location"])
                    continue
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("Website Source must provide uncompressed content")
                length = response.headers.get("content-length")
                if length is not None and int(length) > max_bytes:
                    raise ValueError("Website Source exceeds the download limit")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > max_bytes:
                        raise ValueError("Website Source exceeds the download limit")
                    body.extend(chunk)
                return current, bytes(body)
    raise ValueError("Website Source has too many redirects")


async def afetch_public_page(url: str, max_bytes: int = 4 * 1024 * 1024, deadline: float = 30) -> Tuple[str, bytes]:
    """Bound DNS, redirects and streaming together, including slow trickle responses."""
    return await asyncio.wait_for(_fetch(url, max_bytes), timeout=deadline)


def fetch_public_page(url: str, max_bytes: int = 4 * 1024 * 1024, deadline: float = 30) -> Tuple[str, bytes]:
    """Synchronous counterpart, also usable by synchronous SDK code inside an event loop."""

    def run():
        return asyncio.run(afetch_public_page(url, max_bytes, deadline))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(run).result()
