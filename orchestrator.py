# orchestrator.py
# Orchestrates crawling, extraction, scoring, and output.

from crawler.queue_worker import QueueWorker
from extractor.parser import extract_code_snippets
from scorer.heuristics import is_windows_biased
from scorer.llm_client import LLMClient
from webui.db import SessionLocal
from webui.models import Scan, Page, Snippet
import csv
import json
import os
import sys
import asyncio
import aiohttp
import datetime

BASE_URL = "https://learn.microsoft.com/en-us/azure/virtual-network"
RESULTS_DIR = "results"
MAX_PAGES = 1000

async def main(url=None):
    db = SessionLocal()
    scan = Scan(url=url, status='running')
    db.add(scan)
    db.commit()
    db.refresh(scan)
    # Crawl phase (incremental progress)
    crawled_results = {}
    page_objs = {}
    worker = QueueWorker(url or BASE_URL)
    worker.session = await aiohttp.ClientSession().__aenter__()
    await worker.to_visit.put(worker.base_url)
    while not worker.to_visit.empty() and len(worker.seen) < MAX_PAGES:
        page_url = await worker.to_visit.get()
        if page_url in worker.seen:
            continue
        # Skip any page where 'windows' appears anywhere in the URL (substring match)
        if 'windows' in page_url.lower():
            continue
        worker.seen.add(page_url)
        html = await worker.fetcher.fetch(page_url, worker.session)
        if html:
            crawled_results[page_url] = html
            page_obj = Page(scan_id=scan.id, url=page_url, status='crawled')
            db.add(page_obj)
            db.commit()
            page_objs[page_url] = page_obj
            for link in worker.extract_links(html, page_url):
                if link not in worker.seen:
                    await worker.to_visit.put(link)
        write_progress("crawling", pages=list(crawled_results.keys()), current_url=page_url)
    await worker.session.close()
    html_map = crawled_results
    print(f"[INFO] Crawled {len(html_map)} pages.")
    write_progress("crawled", pages=list(html_map.keys()))

    if not html_map:
        scan.status = 'error'
        db.commit()
        print("[ERROR] No pages crawled. Check network, robots.txt, or crawling logic.")
        return

    # Extraction phase
    print("[INFO] Extracting code snippets from crawled pages...")
    all_snippets = []
    for url, html in html_map.items():
        if not html:
            print(f"[WARN] No HTML for {url}")
            continue
        snippets = extract_code_snippets(html)
        print(f"[DEBUG] {url}: {len(snippets)} <pre> blocks found.")
        page_obj = page_objs.get(url)
        for snip in snippets:
            snip['url'] = url
            snippet_obj = Snippet(page_id=page_obj.id, context=snip['context'], code=snip['code'])
            db.add(snippet_obj)
            db.commit()
            all_snippets.append(snip)
        write_progress("extracting", pages=html_map.keys(), snippets=all_snippets, current_url=url)
    print(f"[INFO] Extracted {len(all_snippets)} code snippets.")

    if not all_snippets:
        scan.status = 'error'
        db.commit()
        print("[ERROR] No code snippets extracted. Check extraction logic or HTML structure.")
        return

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
    write_progress("heuristics", pages=html_map.keys(), snippets=all_snippets, flagged=flagged)

    if not flagged:
        flagged = all_snippets

    # LLM phase
    print("[INFO] Scoring flagged snippets with LLM...")
    llm = LLMClient()
    for i, snip in enumerate(flagged):
        print(f"[LLM] Scoring snippet {i+1}/{len(flagged)} from {snip['url']}")
        snip['llm_score'] = llm.score_snippet(snip)
        snippet_obj = db.query(Snippet).join(Page).filter(Page.url == snip['url'], Snippet.code == snip['code']).first()
        if snippet_obj:
            snippet_obj.llm_score = snip['llm_score']
            db.commit()
        write_progress("llm", pages=html_map.keys(), snippets=all_snippets, flagged=flagged[:i+1], current_url=snip['url'])
    scan.status = 'done'
    scan.finished_at = datetime.datetime.utcnow()
    db.commit()
    print(f"[INFO] Results written to database.")

def write_progress(stage, pages=None, snippets=None, flagged=None, current_url=None):
    progress_path = os.path.join(RESULTS_DIR, "scan_progress.json")
    d = {
        "stage": stage,
        "pages": list(pages) if pages else [],
        "snippets": len(snippets) if snippets else 0,
        "flagged": len(flagged) if flagged else 0,
        "current_url": current_url
    }
    with open(progress_path, "w") as f:
        json.dump(d, f)

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(url))
