"""
CrawlerService - Handles web crawling functionality
Extracted from the monolithic queue_worker.py
"""
import asyncio
import aiohttp
from urllib.parse import urljoin, urlparse
import re
import hashlib
from datetime import datetime
from typing import Optional, Dict
from bs4 import BeautifulSoup
from fetcher import Fetcher
from shared.config import config


class CrawlerService:
    """Service responsible for web crawling operations"""
    
    def __init__(self, base_url: str, rate_per_sec: int = None, user_agent: str = None):
        self.base_url = base_url
        self.seen = set()
        self.to_visit = asyncio.Queue()
        self.session = None
        
        # Use configuration values with fallbacks
        rate_per_sec = rate_per_sec or config.application.rate_limit_per_sec
        user_agent = user_agent or config.application.user_agent
        
        self.fetcher = Fetcher(rate_per_sec, user_agent)

    def is_valid_url(self, url: str) -> bool:
        """Check if URL is valid for crawling (under base URL)"""
        return url.startswith(self.base_url)

    def is_windows_focused_url(self, url: str) -> bool:
        """Check if URL appears to be Windows-focused based on path"""
        url = url.lower()
        return (
            'windows' in url or
            '/powershell/' in url or
            '/cmd/' in url or
            '/cli-windows/' in url
        )

    def is_windows_focused_heading(self, html: str) -> bool:
        """Check if page has Windows-focused heading"""
        match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
        if match:
            heading = match.group(1).lower()
            return 'windows' in heading
        return False

    def extract_links(self, html: str, current_url: str) -> set:
        """Extract valid links from HTML content"""
        links = set()
        soup = BeautifulSoup(html, 'html.parser')
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            
            # Skip media directories
            if '/media/' in href or href.strip('/').endswith('/media'):
                continue
                
            # Convert relative URLs to absolute
            if href.startswith('http'):
                url = href
            else:
                url = urljoin(current_url, href)
                
            # Skip media directories after URL joining
            if '/media/' in url or url.strip('/').endswith('/media'):
                continue
                
            if self.is_valid_url(url):
                # Skip non-HTML resources by extension
                if re.search(r'\.(png|jpg|jpeg|gif|svg|pdf|zip|tar|gz|mp4|mp3|webm|ico|css|js)(\?|$)', url, re.IGNORECASE):
                    continue
                links.add(url.split('#')[0])
                
        print(f"[DEBUG] Found {len(links)} links on {current_url}")
        return links

    async def crawl(self, max_pages: Optional[int] = None) -> dict:
        """
        Crawl pages starting from base_url
        
        Args:
            max_pages: Maximum number of pages to crawl (None = unlimited)
            
        Returns:
            Dictionary mapping URLs to their HTML content
        """
        max_pages = max_pages if max_pages is not None else config.application.max_pages
        
        self.session = aiohttp.ClientSession()
        await self.to_visit.put(self.base_url)
        results = {}
        
        try:
            while not self.to_visit.empty() and (max_pages is None or len(self.seen) < max_pages):
                url = await self.to_visit.get()
                
                if url in self.seen:
                    continue
                    
                if self.is_windows_focused_url(url):
                    continue
                    
                self.seen.add(url)
                html = await self.fetcher.fetch(url, self.session)
                
                if html and not self.is_windows_focused_heading(html):
                    results[url] = html
                    
                    # Add new links to queue
                    for link in self.extract_links(html, url):
                        if link not in self.seen:
                            await self.to_visit.put(link)
                            
        finally:
            await self.session.close()
            
        return results

    def extract_snippets(self, html: str) -> list:
        """
        Extract code snippets from HTML content
        
        Args:
            html: HTML content to extract snippets from
            
        Returns:
            List of dictionaries containing code snippets and context
        """
        soup = BeautifulSoup(html, 'html.parser')
        snippets = []
        
        for pre in soup.find_all('pre'):
            context = ''
            
            # Try to find context from parent elements
            parent = pre.find_parent(['section', 'article', 'div'])
            if parent:
                heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if heading:
                    context = heading.get_text(strip=True)
                    
            # Fallback: look for previous heading
            if not context:
                prev = pre.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if prev:
                    context = prev.get_text(strip=True)
                    
            code = pre.get_text('\n', strip=True)
            
            # Check if under Azure PowerShell tab
            under_az_powershell_tab = False
            tab_parent = pre.find_parent(attrs={"data-tab": True})
            if tab_parent and tab_parent.get("data-tab", "").lower() == "azure-powershell":
                under_az_powershell_tab = True
                
            # Check if context/header contains 'windows'
            windows_header = bool(context and 'windows' in context.lower())
            
            snippets.append({
                'code': code,
                'context': context,
                'under_az_powershell_tab': under_az_powershell_tab,
                'windows_header': windows_header
            })
            
        return snippets

    def calculate_content_hash(self, html_content: str) -> str:
        """
        Calculate SHA256 hash of HTML content for change detection
        
        Args:
            html_content: HTML content to hash
            
        Returns:
            SHA256 hash as hexadecimal string
        """
        return hashlib.sha256(html_content.encode('utf-8')).hexdigest()

    async def get_page_metadata(self, url: str) -> Optional[Dict[str, str]]:
        """
        Get metadata for a web page including content hash and last-modified date
        
        Args:
            url: URL to fetch metadata for
            
        Returns:
            Dictionary with 'content_hash', 'last_modified', and 'url' keys, or None if error
        """
        try:
            session = aiohttp.ClientSession()
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.text()
                        last_modified = response.headers.get('Last-Modified')
                        
                        # Parse last-modified header if present
                        last_modified_dt = None
                        if last_modified:
                            try:
                                from email.utils import parsedate_to_datetime
                                last_modified_dt = parsedate_to_datetime(last_modified)
                            except Exception:
                                last_modified_dt = None
                        
                        return {
                            'content_hash': self.calculate_content_hash(content),
                            'last_modified': last_modified_dt.isoformat() if last_modified_dt else None,
                            'url': url,
                            'status_code': response.status
                        }
            finally:
                await session.close()
                
        except Exception as e:
            print(f"[ERROR] Could not fetch metadata for URL {url}: {e}")
            return None

    def has_content_changed(self, current_hash: str, new_content: str) -> bool:
        """
        Check if web content has changed by comparing hashes
        
        Args:
            current_hash: Current content hash to compare against
            new_content: New HTML content to check
            
        Returns:
            True if content has changed, False if unchanged
        """
        new_hash = self.calculate_content_hash(new_content)
        return new_hash != current_hash