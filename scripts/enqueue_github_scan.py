#!/usr/bin/env python3
"""
Simple script to enqueue a GitHub scan task for Azure docs
Used by Kubernetes CronJob to schedule hourly scans
"""
import os
import sys
import json
import pika
from datetime import datetime

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.utils.database import SessionLocal
from shared.models import Scan
from shared.utils.url_utils import detect_url_source
from shared.config import get_repo_scan_urls


def enqueue_scan_task(url, scan_id, source, force_rescan=False):
    """Enqueue a scan task to RabbitMQ (copied from webui/routes/scan.py)"""
    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
    RABBITMQ_USERNAME = os.getenv("RABBITMQ_USERNAME", "guest")
    RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
    
    print(f"[INFO] Connecting to RabbitMQ at {RABBITMQ_HOST}")
    
    credentials = pika.PlainCredentials(RABBITMQ_USERNAME, RABBITMQ_PASSWORD)
    connection = pika.BlockingConnection(pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials
    ))
    channel = connection.channel()
    channel.queue_declare(queue='scan_tasks', durable=True)
    
    task_data = {
        "url": url,
        "scan_id": scan_id,
        "source": source,
        "force_rescan": force_rescan
    }
    message = json.dumps(task_data)
    print(f"[DEBUG] Enqueueing message: {message}")
    
    print(f"[INFO] Enqueuing scan task: url={url}, scan_id={scan_id}, source={source}, force_rescan={force_rescan}")
    channel.basic_publish(
        exchange='',
        routing_key='scan_tasks',
        body=message,
        properties=pika.BasicProperties(delivery_mode=2)  # Persistent
    )
    
    queue_state = channel.queue_declare(queue='scan_tasks', passive=True)
    print(f"[INFO] scan_tasks queue message count after publish: {queue_state.method.message_count}")
    
    connection.close()


def main():
    """Main function to create scan records and enqueue tasks for all tracked repos"""
    print(f"[INFO] Starting scheduled GitHub scan at {datetime.utcnow()}")

    # Get all repo URLs from config
    repo_urls = get_repo_scan_urls()
    print(f"[INFO] Found {len(repo_urls)} repositories to scan")

    db = SessionLocal()
    try:
        for url in repo_urls:
            print(f"[INFO] Processing: {url}")

            # Create a new scan record for this repo
            new_scan = Scan(
                url=url,
                started_at=datetime.utcnow(),
                status="in_progress"
            )
            db.add(new_scan)
            db.commit()
            db.refresh(new_scan)
            scan_id = new_scan.id

            print(f"[INFO] Created scan record with ID: {scan_id}")

            # Enqueue the scan task with force_rescan=False for change detection
            source = detect_url_source(url)
            print(f"[DEBUG] About to enqueue task with url='{url}', scan_id={scan_id}, source='{source}'")
            enqueue_scan_task(url, scan_id, source, force_rescan=False)

            print(f"[INFO] Successfully enqueued GitHub scan task for scan ID: {scan_id}")

        print(f"[INFO] Completed enqueueing scans for all {len(repo_urls)} repositories")

    except Exception as e:
        print(f"[ERROR] Failed to create scan record or enqueue task: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()