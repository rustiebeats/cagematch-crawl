import asyncio
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cagematch.net/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class Fetcher:
    def __init__(self, delay: float = 1.5, concurrency: int = 3, max_retries: int = 3):
        self.delay = delay
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=HEADERS,
            http2=True,
            timeout=30.0,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def fetch(self, params: dict) -> BeautifulSoup:
        async with self.semaphore:
            for attempt in range(self.max_retries):
                try:
                    resp = await self._client.get("", params=params)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        wait = (2 ** attempt) * self.delay
                        logger.warning(
                            "HTTP %s for %s, retry in %.1fs",
                            resp.status_code, params, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    await asyncio.sleep(self.delay)
                    return BeautifulSoup(resp.text, "lxml")
                except httpx.TransportError as exc:
                    wait = (2 ** attempt) * self.delay
                    logger.warning("Transport error %s, retry in %.1fs", exc, wait)
                    await asyncio.sleep(wait)
            raise RuntimeError(f"Failed to fetch {params} after {self.max_retries} retries")
