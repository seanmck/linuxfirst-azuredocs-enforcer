# fetcher.py
# Implements async HTML fetching with aiohttp, rate-limiting, and robots.txt compliance.

import aiohttp
import asyncio
import async_timeout
import time
import re
from urllib.parse import urlparse, urljoin
from urllib import robotparser

class RateLimiter:
    def __init__(self, rate_per_sec):
        self.rate_per_sec = rate_per_sec
        self.last_called = 0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            wait_time = max(0, (1 / self.rate_per_sec) - (now - self.last_called))
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self.last_called = time.monotonic()

class RobotsCache:
    def __init__(self):
        self.parsers = {}

    async def allowed(self, session, url, user_agent='*'):
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self.parsers:
            robots_url = urljoin(base, '/robots.txt')
            try:
                async with session.get(robots_url) as resp:
                    text = await resp.text()
            except Exception:
                text = ''
            rp = robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.parse(text.splitlines())
            self.parsers[base] = rp
        return self.parsers[base].can_fetch(user_agent, url)

class Fetcher:
    def __init__(self, rate_per_sec=2, user_agent='linuxfirst-crawler'):
        self.rate_limiter = RateLimiter(rate_per_sec)
        self.user_agent = user_agent
        self.robots = RobotsCache()

    async def fetch(self, url, session, timeout=15):
        await self.rate_limiter.wait()
        if not await self.robots.allowed(session, url, self.user_agent):
            print(f"Blocked by robots.txt: {url}")
            return None
        headers = {'User-Agent': self.user_agent}
        try:
            async with async_timeout.timeout(timeout):
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200 and 'text/html' in resp.headers.get('Content-Type', ''):
                        return await resp.text()
                    else:
                        print(f"Non-HTML or error ({resp.status}): {url}")
                        return None
        except Exception as e:
            print(f"Fetch error for {url}: {e}")
            return None

async def fetch_all(urls, rate_per_sec=2, user_agent='linuxfirst-crawler'):
    fetcher = Fetcher(rate_per_sec, user_agent)
    async with aiohttp.ClientSession() as session:
        tasks = [fetcher.fetch(url, session) for url in urls]
        return await asyncio.gather(*tasks)

# Example usage (for testing):
# if __name__ == "__main__":
#     urls = ["https://learn.microsoft.com/en-us/azure/"]
#     htmls = asyncio.run(fetch_all(urls))
#     print(htmls[0][:1000])
