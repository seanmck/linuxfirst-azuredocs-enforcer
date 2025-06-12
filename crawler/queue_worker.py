# queue_worker.py
# Manages the URL queue and orchestrates crawling tasks.

import asyncio
import aiohttp
from .fetcher import Fetcher
from urllib.parse import urljoin, urlparse
import re

class QueueWorker:
    def __init__(self, base_url, rate_per_sec=2, user_agent='linuxfirst-crawler'):
        self.base_url = base_url
        self.seen = set()
        self.to_visit = asyncio.Queue()
        self.fetcher = Fetcher(rate_per_sec, user_agent)
        self.session = None

    def is_valid_url(self, url):
        # Only crawl under the Azure docs base path
        return url.startswith(self.base_url)

    def is_windows_focused_url(self, url):
        url = url.lower()
        # Skip any page where 'windows' appears anywhere in the URL (substring match)
        return (
            'windows' in url or
            '/powershell/' in url or
            '/cmd/' in url or
            '/cli-windows/' in url
        )

    def is_windows_focused_heading(self, html):
        # Look for a top-level heading (h1) containing 'Windows'
        import re
        match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE|re.DOTALL)
        if match:
            heading = match.group(1).lower()
            return 'windows' in heading
        return False

    def extract_links(self, html, current_url):
        # Simple regex for hrefs (could use BeautifulSoup for robustness)
        links = set()
        for match in re.findall(r'href=["\'](.*?)["\']', html):
            if match.startswith('http'):
                url = match
            else:
                url = urljoin(current_url, match)
            if self.is_valid_url(url):
                # Skip non-HTML resources by extension
                if re.search(r'\.(png|jpg|jpeg|gif|svg|pdf|zip|tar|gz|mp4|mp3|webm|ico|css|js)(\?|$)', url, re.IGNORECASE):
                    continue
                links.add(url.split('#')[0])
        return links

    async def crawl(self, max_pages=1000):
        self.session = aiohttp.ClientSession()
        await self.to_visit.put(self.base_url)
        results = {}
        while not self.to_visit.empty() and len(self.seen) < max_pages:
            url = await self.to_visit.get()
            if url in self.seen:
                continue
            if self.is_windows_focused_url(url):
                continue
            self.seen.add(url)
            html = await self.fetcher.fetch(url, self.session)
            if html and not self.is_windows_focused_heading(html):
                results[url] = html
                for link in self.extract_links(html, url):
                    if link not in self.seen:
                        await self.to_visit.put(link)
        await self.session.close()
        return results

# Example usage (for testing):
# if __name__ == "__main__":
#     worker = QueueWorker("https://learn.microsoft.com/en-us/azure/")
#     htmls = asyncio.run(worker.crawl(10))
#     print(list(htmls.keys()))
