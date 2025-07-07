from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class Scan(Base):
    __tablename__ = 'scans'
    id = Column(Integer, primary_key=True)
    url = Column(String, nullable=True)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, default='running')
    biased_pages_count = Column(Integer, default=0)
    flagged_snippets_count = Column(Integer, default=0)
    
    # New progress tracking fields
    current_phase = Column(String, nullable=True)  # crawling, extracting, scoring, mcp_holistic, done
    current_page_url = Column(String, nullable=True)  # currently processing page
    total_pages_found = Column(Integer, default=0)  # total pages discovered
    pages_processed = Column(Integer, default=0)  # pages completed in current phase
    snippets_processed = Column(Integer, default=0)  # snippets processed
    phase_progress = Column(JSON, nullable=True)  # detailed progress per phase
    error_log = Column(JSON, nullable=True)  # real-time error tracking
    phase_timestamps = Column(JSON, nullable=True)  # start/end times per phase
    estimated_completion = Column(DateTime, nullable=True)  # ETA calculation
    performance_metrics = Column(JSON, nullable=True)  # pages/sec, etc.
    
    # Cancellation fields
    cancellation_requested = Column(Boolean, default=False)  # whether cancellation was requested
    cancellation_requested_at = Column(DateTime, nullable=True)  # when cancellation was requested
    cancellation_reason = Column(String, nullable=True)  # reason for cancellation
    
    pages = relationship("Page", back_populates="scan")

class Page(Base):
    __tablename__ = 'pages'
    id = Column(Integer, primary_key=True)
    scan_id = Column(Integer, ForeignKey('scans.id'))
    url = Column(String)
    status = Column(String)
    mcp_holistic = Column(JSON)  # Holistic MCP result per page
    
    # Change detection fields
    content_hash = Column(String, nullable=True)  # SHA256 hash of document content
    last_modified = Column(DateTime, nullable=True)  # Last modification timestamp
    github_sha = Column(String, nullable=True)  # GitHub file SHA for repo scans
    last_scanned_at = Column(DateTime, nullable=True)  # When this page was last processed
    
    # Processing lock fields
    processing_started_at = Column(DateTime, nullable=True)  # When processing started
    processing_worker_id = Column(String, nullable=True)  # ID of worker processing this page
    processing_expires_at = Column(DateTime, nullable=True)  # When processing lock expires
    
    scan = relationship("Scan", back_populates="pages")
    snippets = relationship("Snippet", back_populates="page")

class ProcessingUrl(Base):
    __tablename__ = 'processing_urls'
    id = Column(Integer, primary_key=True)
    url = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)
    scan_id = Column(Integer, ForeignKey('scans.id'), nullable=False)
    worker_id = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default='processing')

class Snippet(Base):
    __tablename__ = 'snippets'
    id = Column(Integer, primary_key=True)
    page_id = Column(Integer, ForeignKey('pages.id'))
    context = Column(Text)
    code = Column(Text)
    llm_score = Column(JSON)
    page = relationship("Page", back_populates="snippets")