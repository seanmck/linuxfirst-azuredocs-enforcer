#!/usr/bin/env python3
"""
Script to update daily bias snapshots.

This script should be run daily (via cron or other scheduler) to calculate
and store the current bias state of the documentation corpus.
"""
import os
import sys
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add the parent directory to the path so we can import shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.models import Base
from shared.config import config
from shared.application.bias_snapshot_service import BiasSnapshotService


def main():
    """Main function to update daily bias snapshots"""
    print(f"[{datetime.datetime.now()}] Starting daily bias snapshot update...")
    
    # Create database connection
    engine = create_engine(config.database.url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Create service instance
        service = BiasSnapshotService(db)
        
        # Calculate and save today's snapshots
        overall_snapshot, docset_snapshots = service.calculate_and_save_today()
        
        if overall_snapshot:
            print(f"Successfully saved overall snapshot:")
            print(f"  - Date: {overall_snapshot.date}")
            print(f"  - Total pages: {overall_snapshot.total_pages}")
            print(f"  - Biased pages: {overall_snapshot.biased_pages}")
            print(f"  - Bias percentage: {overall_snapshot.bias_percentage}%")
            
            if docset_snapshots:
                print(f"\nSaved {len(docset_snapshots)} docset snapshots")
                
                # Show top 5 most biased docsets
                top_biased = sorted(
                    docset_snapshots,
                    key=lambda x: x.bias_percentage,
                    reverse=True
                )[:5]
                
                print("\nTop 5 most biased documentation sets:")
                for i, snapshot in enumerate(top_biased, 1):
                    print(f"  {i}. {snapshot.doc_set}: {snapshot.bias_percentage}% bias ({snapshot.biased_pages}/{snapshot.total_pages} pages)")
        else:
            print("No data available to create snapshot for today")
            
        print(f"\n[{datetime.datetime.now()}] Bias snapshot update completed successfully")
        
    except Exception as e:
        print(f"\n[{datetime.datetime.now()}] ERROR: Failed to update bias snapshots: {str(e)}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()