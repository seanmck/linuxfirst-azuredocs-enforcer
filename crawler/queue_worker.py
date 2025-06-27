# queue_worker.py
# Manages the URL queue and orchestrates crawling tasks.

import sys
import os
import time
import random

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

import asyncio
import aiohttp
from crawler.fetcher import Fetcher
from urllib.parse import urljoin, urlparse
import re
import pika
from sqlalchemy.orm import sessionmaker
from webui.models import Page, Snippet, Scan
from webui.db import SessionLocal
from scorer.heuristics import is_windows_biased
from bs4 import BeautifulSoup
from scorer.llm_client import LLMClient
import json
from github import Github
import httpx

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
        # Use BeautifulSoup for robust link extraction
        links = set()
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/media/' in href or href.strip('/').endswith('/media'):
                continue  # Skip links to any media directory
            if href.startswith('http'):
                url = href
            else:
                url = urljoin(current_url, href)
            if '/media/' in url or url.strip('/').endswith('/media'):
                continue  # Skip links to any media directory
            if self.is_valid_url(url):
                # Skip non-HTML resources by extension
                if re.search(r'\.(png|jpg|jpeg|gif|svg|pdf|zip|tar|gz|mp4|mp3|webm|ico|css|js)(\?|$)', url, re.IGNORECASE):
                    continue
                links.add(url.split('#')[0])
        print(f"[DEBUG] Found {len(links)} links on {current_url}")
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

    def process_scan_task(self, url, scan_id):
        print(f"[DEBUG] Starting full scan pipeline for URL: {url}, scan_id: {scan_id}")
        db = SessionLocal()
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            print(f"[ERROR] Scan with ID {scan_id} not found")
            db.close()
            return
        print(f"[INFO] Using existing scan ID: {scan_id}")
        scan.status = 'crawling'
        db.commit()

        # Crawl phase
        crawled_results = {}
        page_objs = {}
        worker = QueueWorker(url)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        crawled_results = loop.run_until_complete(worker.crawl(1000))
        for page_url, html in crawled_results.items():
            page_obj = Page(scan_id=scan.id, url=page_url, status='crawled')
            db.add(page_obj)
            db.commit()
            page_objs[page_url] = page_obj
        print(f"[INFO] Crawled {len(crawled_results)} pages.")
        scan.status = 'extracting'
        db.commit()

        # Extraction phase
        print("[INFO] Extracting code snippets from crawled pages...")
        all_snippets = []
        from extractor.parser import extract_code_snippets
        for i, (page_url, html) in enumerate(crawled_results.items()):
            snippets = extract_code_snippets(html)
            page_obj = page_objs.get(page_url)
            for snip in snippets:
                snip['url'] = page_url
                snippet_obj = Snippet(page_id=page_obj.id, context=snip['context'], code=snip['code'])
                db.add(snippet_obj)
                db.commit()
                all_snippets.append(snip)
        print(f"[INFO] Extracted {len(all_snippets)} code snippets.")
        if not all_snippets:
            scan.status = 'error'
            db.commit()
            print("[ERROR] No code snippets extracted. Check extraction logic or HTML structure.")
            db.close()
            return
        scan.status = 'scoring'
        db.commit()

        # Heuristic phase
        print("[INFO] Applying Windows bias heuristics...")
        flagged = []
        for s in all_snippets:
            if is_windows_biased(s):
                flagged.append(s)
                snippet_obj = db.query(Snippet).join(Page).filter(Page.url == s['url'], Snippet.code == s['code']).first()
                if snippet_obj:
                    if not snippet_obj.llm_score:
                        snippet_obj.llm_score = {}
                    snippet_obj.llm_score['heuristic_biased'] = True
                    db.commit()
        print(f"[INFO] {len(flagged)} snippets flagged by heuristics.")
        if not flagged:
            flagged = all_snippets

        # LLM phase
        print("[INFO] Scoring flagged snippets with LLM...")
        from scorer.llm_client import LLMClient
        llm = LLMClient()
        for i, snip in enumerate(flagged):
            print(f"[LLM] Scoring snippet {i+1}/{len(flagged)} from {snip['url']}")
            snip['llm_score'] = llm.score_snippet(snip)
            snippet_obj = db.query(Snippet).join(Page).filter(Page.url == snip['url'], Snippet.code == snip['code']).first()
            if snippet_obj:
                snippet_obj.llm_score = snip['llm_score']
                db.commit()

        # MCP holistic scoring phase
        print("[INFO] Scoring full pages holistically with MCP server...")
        mcp_url = os.getenv("MCP_SERVER_URL", "http://localhost:8001/score_page")
        for page_url, page_obj in page_objs.items():
            html = crawled_results.get(page_url)
            if not html:
                continue
            page_content = html
            try:
                print(f"[MCP] Sending page to MCP server: {page_url}")
                resp = httpx.post(mcp_url, json={"page_content": page_content, "metadata": {"url": page_url}}, timeout=60)
                print(f"[MCP] MCP server response status: {resp.status_code}")
                if resp.status_code == 200:
                    mcp_result = resp.json()
                    print(f"[MCP] Holistic score for {page_url}: {mcp_result}")
                    # Store holistic MCP result in the Page object
                    if page_obj:
                        page_obj.mcp_holistic = mcp_result
                        db.commit()
                else:
                    print(f"[MCP] Error from MCP server for {page_url}: {resp.status_code} {resp.text}")
            except Exception as e:
                print(f"[MCP] Exception contacting MCP server for {page_url}: {e}")
        scan.status = 'done'
        import datetime
        scan.finished_at = datetime.datetime.utcnow()
        scan.biased_pages_count = len(set([s['url'] for s in flagged]))
        scan.flagged_snippets_count = len(flagged)
        db.commit()
        print(f"[INFO] Results written to database.")
        print(f"[INFO] Updated scan metrics: {scan.biased_pages_count} biased pages, {scan.flagged_snippets_count} flagged snippets.")
        db.close()

    def consume_from_queue(self):
        print("[DEBUG] Queue worker script started.")
        try:
            print("[DEBUG] Attempting to connect to RabbitMQ...")
            RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
            print(f"[DEBUG] queue_worker.py using RABBITMQ_HOST={RABBITMQ_HOST} for scan_tasks queue")
            connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
            print("[DEBUG] Connection to RabbitMQ established.")
            channel = connection.channel()
            print("[DEBUG] Declaring queue 'scan_tasks'...")
            channel.queue_declare(queue='scan_tasks')
            print("[DEBUG] Queue 'scan_tasks' declared.")
            # Output the number of messages in the queue at startup
            queue_state = channel.queue_declare(queue='scan_tasks', passive=True)
            print(f"[DEBUG] scan_tasks queue message count at startup: {queue_state.method.message_count}")

            def callback(ch, method, properties, body):
                print(f"[INFO] Received task: {body.decode()}")
                print("[DEBUG] Starting task processing...")
                try:
                    task_data_raw = body.decode()
                    print(f"[DEBUG] Raw task data: {task_data_raw}")
                    task_data = json.loads(task_data_raw)
                    url = task_data.get('url')
                    scan_id = task_data.get('scan_id')
                    source = task_data.get('source', 'web')
                    print(f"[DEBUG] Parsed url: {url}, scan_id: {scan_id}, source: {source}")
                    if not url or not scan_id:
                        print(f"[ERROR] Invalid task data: missing url or scan_id in {task_data_raw}")
                        return
                    print(f"[DEBUG] Processing URL: {url} for scan_id: {scan_id} (source: {source})")
                    if source == 'github':
                        self.process_github_scan_task(url, scan_id)
                    else:
                        self.process_scan_task(url, scan_id)
                    print(f"[INFO] Successfully processed task: {url} for scan_id: {scan_id}")
                except json.JSONDecodeError as e:
                    print(f"[ERROR] Failed to parse JSON task data: {task_data_raw}. Error: {e}")
                except Exception as e:
                    print(f"[ERROR] Failed to process task: {task_data_raw}. Error: {e}")

            print("[DEBUG] Starting to consume messages from 'scan_tasks' queue...")
            channel.basic_consume(queue='scan_tasks', on_message_callback=callback, auto_ack=True)
            channel.start_consuming()
        except Exception as e:
            print(f"[ERROR] An unexpected error occurred during initialization: {e}")
            import traceback
            traceback.print_exc()

    def process_github_scan_task(self, url, scan_id):
        print(f"[DEBUG] Starting GitHub scan pipeline for repo: {url}, scan_id: {scan_id}")
        github_token = os.environ.get('GITHUB_TOKEN')
        if not github_token:
            print("[ERROR] GITHUB_TOKEN not set in environment. Cannot scan GitHub repo.")
            return
        # Parse repo and path from URL
        m = re.match(r'https://github.com/([^/]+/[^/]+)(/tree/[^/]+(/.*)?)?', url)
        if not m:
            print(f"[ERROR] Could not parse GitHub repo from URL: {url}")
            return
        repo_full_name = m.group(1)
        path = m.group(3) or ''
        print(f"[DEBUG] Parsed repo: {repo_full_name}, path: {path}")
        g = Github(github_token)
        repo = g.get_repo(repo_full_name)
        # Default to 'main' branch
        branch = 'main'
        if '/tree/' in url:
            branch_match = re.search(r'/tree/([^/]+)', url)
            if branch_match:
                branch = branch_match.group(1)
        print(f"[DEBUG] Using branch: {branch}")

        def list_md_files_iterative(repo, start_path, branch, max_files=500, max_dirs=100, min_delay=0.5, max_delay=2.0, progress_file=None):
            files = []
            dirs_to_process = [start_path]
            dirs_seen = 0
            processed_dirs = set()
            if progress_file and os.path.exists(progress_file):
                try:
                    with open(progress_file, 'r') as pf:
                        import json
                        state = json.load(pf)
                        files = state.get('files', [])
                        dirs_to_process = state.get('dirs_to_process', [start_path])
                        dirs_seen = state.get('dirs_seen', 0)
                        processed_dirs = set(state.get('processed_dirs', []))
                    print(f"[DEBUG] Resuming from progress file: {progress_file}")
                except Exception as e:
                    print(f"[ERROR] Failed to load progress file: {e}")
            while dirs_to_process and len(files) < max_files:
                current_dir = dirs_to_process.pop(0)
                if current_dir in processed_dirs:
                    print(f"[DEBUG] Skipping already processed directory: {current_dir}")
                    dirs_seen += 1
                    continue
                print(f"[DEBUG] Fetching contents of: {current_dir}")
                try:
                    contents = repo.get_contents(current_dir, ref=branch)
                except Exception as e:
                    print(f"[ERROR] Exception in get_contents for {current_dir}: {e}")
                    # Exponential backoff on error
                    delay = min(max_delay, min_delay * (2 ** dirs_seen))
                    print(f"[DEBUG] Sleeping for {delay:.2f}s before retrying...")
                    time.sleep(delay)
                    continue
                dirs_seen += 1
                processed_dirs.add(current_dir)
                for content_file in contents:
                    if content_file.type == 'dir':
                        dirs_to_process.append(content_file.path)
                    elif content_file.path.endswith('.md'):
                        files.append({
                            'path': content_file.path,
                            'sha': content_file.sha
                        })
                        if len(files) >= max_files:
                            print(f"[DEBUG] Reached max_files={max_files}")
                            break
                # Persist progress
                if progress_file:
                    try:
                        with open(progress_file, 'w') as pf:
                            import json
                            json.dump({
                                'files': files,
                                'dirs_to_process': dirs_to_process,
                                'dirs_seen': dirs_seen,
                                'processed_dirs': list(processed_dirs)
                            }, pf)
                    except Exception as e:
                        print(f"[ERROR] Failed to write progress file: {e}")
                # Add a small random delay to avoid rate limiting
                delay = random.uniform(min_delay, max_delay)
                print(f"[DEBUG] Sleeping for {delay:.2f}s to avoid rate limiting...")
                time.sleep(delay)
            print(f"[DEBUG] Total .md files found: {len(files)}")
            return files

        progress_file = f"github_scan_progress_{scan_id}.json"
        md_file_dicts = list_md_files_iterative(repo, path, branch, max_files=500, max_dirs=100, progress_file=progress_file)
        print(f"[INFO] Found {len(md_file_dicts)} markdown files in repo/path.")
        print(f"[DEBUG] Writing {len(md_file_dicts)} pages and their snippets to the database for scan_id {scan_id}")
        db = SessionLocal()
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            print(f"[ERROR] Scan with ID {scan_id} not found")
            db.close()
            return
        scan.status = 'crawling'
        db.commit()
        page_objs = {}
        for md_file in md_file_dicts:
            page_url = f"https://github.com/{repo_full_name}/blob/{branch}/{md_file['path']}"
            if self.is_windows_focused_url(page_url):
                print(f"[DEBUG] Skipping Windows-focused file: {page_url}")
                continue
            try:
                file_content_obj = repo.get_contents(md_file['path'], ref=branch)
                file_content = file_content_obj.decoded_content.decode()
                h1_match = re.search(r'^# (.+)$', file_content, re.MULTILINE)
                if h1_match and 'powershell' in h1_match.group(1).lower():
                    continue
            except Exception as e:
                print(f"[ERROR] Could not fetch file {md_file['path']}: {e}")
                continue
            page_obj = Page(scan_id=scan.id, url=page_url, status='crawled')
            db.add(page_obj)
            db.commit()
            page_objs[md_file['path']] = page_obj
            # Extract code blocks
            code_blocks = re.findall(r'```(?:[a-zA-Z0-9]*)\n(.*?)```', file_content, re.DOTALL)
            print(f"[DEBUG] {md_file['path']}: {len(code_blocks)} code blocks extracted.")
            for code in code_blocks:
                snippet = Snippet(page_id=page_obj.id, context='', code=code, llm_score=None)
                db.add(snippet)
            db.commit()
        print(f"[DEBUG] Finished writing all pages and snippets for scan_id {scan_id}")

        # LLM phase (added for GitHub scan)
        print("[INFO] Scoring GitHub snippets with LLM...")
        from scorer.llm_client import LLMClient
        llm = LLMClient()
        all_snippets = db.query(Snippet).join(Page).filter(Page.scan_id == scan.id).all()
        flagged = all_snippets  # Optionally, you could add heuristics here
        for i, snip in enumerate(flagged):
            print(f"[LLM] Scoring snippet {i+1}/{len(flagged)} from {snip.page.url}")
            snip.llm_score = llm.score_snippet({
                'code': snip.code,
                'context': snip.context,
                'url': snip.page.url
            })
            db.commit()

        # MCP holistic scoring phase for GitHub scan
        print("[INFO] Scoring GitHub pages holistically with MCP server...")
        mcp_url = os.getenv("MCP_SERVER_URL", "http://localhost:8001/score_page")
        for md_file in md_file_dicts:
            page_url = f"https://github.com/{repo_full_name}/blob/{branch}/{md_file['path']}"
            page_obj = page_objs.get(md_file['path'])
            try:
                file_content_obj = repo.get_contents(md_file['path'], ref=branch)
                file_content = file_content_obj.decoded_content.decode()
            except Exception as e:
                print(f"[MCP] Could not fetch file for MCP scoring: {md_file['path']}: {e}")
                continue
            try:
                print(f"[MCP] Sending GitHub page to MCP server: {page_url}")
                resp = httpx.post(mcp_url, json={"page_content": file_content, "metadata": {"url": page_url}}, timeout=60)
                print(f"[MCP] MCP server response status: {resp.status_code}")
                if resp.status_code == 200:
                    mcp_result = resp.json()
                    print(f"[MCP] Holistic score for {page_url}: {mcp_result}")
                    # Store holistic MCP result in the Page object
                    if page_obj:
                        page_obj.mcp_holistic = mcp_result
                        db.commit()
                else:
                    print(f"[MCP] Error from MCP server for {page_url}: {resp.status_code} {resp.text}")
            except Exception as e:
                print(f"[MCP] Exception contacting MCP server for {page_url}: {e}")
        scan.status = 'done'
        import datetime
        scan.finished_at = datetime.datetime.now(datetime.UTC)
        scan.biased_pages_count = len(set([s.page.url for s in flagged if s.llm_score and s.llm_score.get('windows_biased')]))
        scan.flagged_snippets_count = len([s for s in flagged if s.llm_score and s.llm_score.get('windows_biased')])
        db.commit()
        db.close()
        print(f"[INFO] GitHub scan for scan_id {scan_id} complete.")

# ...existing code...
def extract_snippets(html):
    """
    Extract code snippets from the given HTML content.
    :param html: The HTML content of a page.
    :return: A list of code snippets.
    """
    soup = BeautifulSoup(html, 'html.parser')
    snippets = []
    for pre in soup.find_all('pre'):
        context = ''
        parent = pre.find_parent(['section', 'article', 'div'])
        if parent:
            heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if heading:
                context = heading.get_text(strip=True)
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
        windows_header = False
        if context and 'windows' in context.lower():
            windows_header = True
        snippets.append({
            'code': code,
            'context': context,
            'under_az_powershell_tab': under_az_powershell_tab,
            'windows_header': windows_header
        })
    return snippets

# Example usage (for testing):
# if __name__ == "__main__":
#     worker = QueueWorker("https://learn.microsoft.com/en-us/azure/")
#     htmls = asyncio.run(worker.crawl(10))
#     print(list(htmls.keys()))
#     worker.consume_from_queue()

if __name__ == "__main__":    
    # Redirect all stdout/stderr to queue_worker.log
    #log_file = open("queue_worker.log", "a")
    #sys.stdout = log_file
    #sys.stderr = log_file
    try:
        print("[DEBUG] Queue worker script starting...")
        worker = QueueWorker("https://learn.microsoft.com/en-us/azure/")
        worker.consume_from_queue()
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred during initialization: {e}")
        import traceback
        traceback.print_exc()
    finally:
        log_file.close()
