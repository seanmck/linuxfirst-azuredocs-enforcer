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
import pika

# Default starting URLs based on scan type
DEFAULT_URLS = {
    "manual": "https://learn.microsoft.com/en-us/azure/virtual-machines/",
    "targeted": "https://learn.microsoft.com/en-us/azure/app-service/", 
    "full": "https://learn.microsoft.com/en-us/azure/"
}

# Fallback to virtual-machines if scan type not recognized
BASE_URL = "https://learn.microsoft.com/en-us/azure/virtual-machines/"
RESULTS_DIR = "results"
MAX_PAGES = 1000

# Determine RabbitMQ host based on environment
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")

# Update send_to_queue function to send scan ID along with URL
def send_to_queue(url, scan_id):
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()
    channel.queue_declare(queue='scan_tasks')
    
    # Send both URL and scan ID as JSON
    task_data = {
        "url": url,
        "scan_id": scan_id
    }
    message = json.dumps(task_data)
    
    channel.basic_publish(exchange='', routing_key='scan_tasks', body=message)
    connection.close()

async def main(url=None, scan_id=None):
    # Only enqueue the scan task, do not run the scan pipeline
    if not url:
        scan_type = os.getenv("SCAN_TYPE", "manual")
        url = DEFAULT_URLS.get(scan_type, BASE_URL)
        print(f"[INFO] Starting {scan_type} scan from: {url}")
    db = SessionLocal()
    if scan_id:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            print(f"[ERROR] Scan with ID {scan_id} not found")
            db.close()
            return
        print(f"[INFO] Using existing scan ID: {scan_id}")
    else:
        print("[ERROR] No scan_id provided to orchestrator. Refusing to create duplicate scan. Exiting.")
        db.close()
        return
    send_to_queue(url, scan.id)
    print(f"[INFO] Task sent to RabbitMQ: {url} (scan_id: {scan.id})")
    db.close()

if __name__ == "__main__":
    debug_msg = f"[DEBUG] orchestrator.py invoked with args: {sys.argv}"
    print(debug_msg)
    try:
        with open("orchestrator_debug.log", "a") as logf:
            logf.write(debug_msg + "\n")
    except Exception as e:
        print(f"[DEBUG] Failed to write to log file: {e}")
    url = sys.argv[1] if len(sys.argv) > 1 else None
    scan_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
    asyncio.run(main(url, scan_id))
