"""Small HTTP adapter: bounded bodies, manual redirects, robots, public IP pinning."""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Self
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from sourcesift.core.config import Limits
from sourcesift.retrieval.urls import RetrievalError, hostname, normalize_url

USER_AGENT = "SourceSift/0.2 (+https://jakevanslyke.com/sourcesift/)"


@dataclass(frozen=True)
class Page:
    """Downloaded bytes and actual final URL; parsing never initiates requests."""

    requested_url: str
    url: str
    body: bytes
    content_type: str


async def public_address(host: str, port: int) -> str:
    """Resolve once; reject mixed public/private DNS answers before connecting."""
    try:
        answers = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except OSError:
        raise RetrievalError("Hostname could not be resolved.") from None
    addresses = [ipaddress.ip_address(answer[4][0]) for answer in answers]
    if not addresses or any(
        not address.is_global or address.is_multicast or address.is_reserved
        for address in addresses
    ):
        raise RetrievalError("Non-public network addresses are not accessible.")
    # Prefer IPv4 where a site advertises IPv6 but the user's network lacks it.
    return str(
        next((address for address in addresses if address.version == 4), addresses[0])
    )


class Fetcher:
    """One run's HTTP budget and robots cache. No cookies, auth, retries, or proxies.

    Connections use a validated public IP with the original Host and TLS SNI.
    Keep-alive is disabled to avoid sharing an IP connection between hostnames.
    Every redirect is checked again, including its robots policy.
    """

    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self.requests = 0
        self._robots: dict[str, RobotFileParser] = {}
        self.client = httpx.AsyncClient(
            timeout=limits.http_timeout_seconds,
            trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.client.aclose()

    async def get(self, url: str, *, robots: bool = True) -> Page:
        """Fetch public content with one timeout covering DNS, redirects, and body."""
        try:
            async with asyncio.timeout(self.limits.http_timeout_seconds):
                return await self._get(url, robots=robots)
        except (httpx.HTTPError, TimeoutError):
            raise RetrievalError("HTTP request failed or timed out.") from None

    async def _get(self, url: str, *, robots: bool) -> Page:
        requested = current = normalize_url(url)
        for _ in range(5):
            if robots:
                await self._check_robots(current)
            if self.requests >= self.limits.max_http_requests:
                raise RetrievalError("HTTP request limit reached.")
            host = hostname(current)
            parts = urlsplit(current)
            address = await public_address(
                host, parts.port or (443 if parts.scheme == "https" else 80)
            )
            pinned = httpx.URL(current).copy_with(host=address)
            self.requests += 1
            # Cookies from one publisher must not influence subsequent requests.
            self.client.cookies.clear()
            async with self.client.stream(
                "GET",
                pinned,
                headers={
                    "Host": parts.netloc,
                    "User-Agent": USER_AGENT,
                    "Accept-Encoding": "identity",
                },
                extensions={"sni_hostname": host},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise RetrievalError("Redirect has no destination.")
                    current = normalize_url(urljoin(current, location))
                    continue
                if not robots and response.status_code in {404, 410}:
                    return Page(requested, current, b"", "text/plain")
                if response.status_code != 200:
                    raise RetrievalError(
                        f"HTTP {response.status_code}; content unavailable."
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    body.extend(chunk)
                    if len(body) > self.limits.max_response_bytes:
                        raise RetrievalError("Response exceeds the byte limit.")
                return Page(
                    requested,
                    current,
                    bytes(body),
                    response.headers.get("content-type", ""),
                )
        raise RetrievalError("Redirect limit reached.")

    async def _check_robots(self, url: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            page = await self._get(origin + "/robots.txt", robots=False)
            policy = RobotFileParser()
            policy.parse(page.body.decode("utf-8", errors="replace").splitlines())
            self._robots[origin] = policy
        if not self._robots[origin].can_fetch("SourceSift", url):
            raise RetrievalError("Publisher robots policy disallows retrieval.")
