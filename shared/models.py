from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, DateTime, JSON, Date, Float
import sqlalchemy as sa
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
    status = Column(String, default='in_progress')
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
    
    # Commit tracking fields for safe incremental scans
    working_commit_sha = Column(String(40), nullable=True)  # Commit SHA being scanned
    last_commit_sha = Column(String(40), nullable=True)  # Last successfully scanned commit SHA
    baseline_type = Column(String(20), nullable=True)  # complete, partial, none
    
    # Scan completion tracking
    total_files_discovered = Column(Integer, default=0)  # Total files discovered
    total_files_queued = Column(Integer, default=0)  # Total files queued
    total_files_completed = Column(Integer, default=0)  # Total files completed
    
    pages = relationship("Page", back_populates="scan")
    file_processing_history = relationship("FileProcessingHistory", back_populates="scan")

class Page(Base):
    __tablename__ = 'pages'
    id = Column(Integer, primary_key=True)
    scan_id = Column(Integer, ForeignKey('scans.id'))
    url = Column(String)
    status = Column(String)
    mcp_holistic = Column(JSON)  # Holistic MCP result per page
    doc_set = Column(String(255), nullable=True)  # Pre-computed docset for performance
    
    # Change detection fields
    content_hash = Column(String, nullable=True)  # SHA256 hash of document content
    last_modified = Column(DateTime, nullable=True)  # Last modification timestamp
    github_sha = Column(String, nullable=True)  # GitHub file SHA for repo scans
    last_scanned_at = Column(DateTime, nullable=True)  # When this page was last processed
    
    # Processing lock fields
    processing_started_at = Column(DateTime, nullable=True)  # When processing started
    processing_worker_id = Column(String, nullable=True)  # ID of worker processing this page
    processing_expires_at = Column(DateTime, nullable=True)  # When processing lock expires
    
    # Retry mechanism fields
    retry_count = Column(Integer, default=0)  # Number of retry attempts
    last_error_at = Column(DateTime, nullable=True)  # When last error occurred
    
    # Enhanced processing state tracking
    processing_state = Column(String(30), nullable=True, default='discovered')  # discovered, queued, processing, completed, failed, skipped_*
    
    scan = relationship("Scan", back_populates="pages")
    snippets = relationship("Snippet", back_populates="page")
    feedback = relationship("UserFeedback", back_populates="page", cascade="all, delete-orphan")

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
    proposed_change_id = Column(String(255), nullable=True)  # Link to proposed changes
    page = relationship("Page", back_populates="snippets")
    feedback = relationship("UserFeedback", back_populates="snippet", cascade="all, delete-orphan")

class BiasSnapshot(Base):
    __tablename__ = 'bias_snapshots'
    date = Column(Date, primary_key=True)
    total_pages = Column(Integer, nullable=False)
    biased_pages = Column(Integer, nullable=False)
    bias_percentage = Column(Float, nullable=False)
    last_calculated_at = Column(DateTime(timezone=True), nullable=False)
    additional_data = Column(JSON, nullable=True)

class BiasSnapshotByDocset(Base):
    __tablename__ = 'bias_snapshots_by_docset'
    date = Column(Date, primary_key=True)
    doc_set = Column(String, primary_key=True)
    total_pages = Column(Integer, nullable=False)
    biased_pages = Column(Integer, nullable=False)
    bias_percentage = Column(Float, nullable=False)

class FileProcessingHistory(Base):
    __tablename__ = 'file_processing_history'
    id = Column(Integer, primary_key=True)
    file_path = Column(String(500), nullable=False)
    github_sha = Column(String(40), nullable=False)
    scan_id = Column(Integer, ForeignKey('scans.id'), nullable=False)
    processed_at = Column(DateTime, nullable=False)
    processing_result = Column(String(20), nullable=False)  # completed, failed, skipped
    processing_duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    snippets_found = Column(Integer, nullable=True, default=0)
    bias_detected = Column(Boolean, nullable=True, default=False)
    worker_id = Column(String(100), nullable=True)
    commit_sha = Column(String(40), nullable=True)
    
    # Relationships
    scan = relationship("Scan", back_populates="file_processing_history")
    
    # Unique constraint
    __table_args__ = (
        sa.UniqueConstraint('file_path', 'github_sha', 'scan_id', name='uq_file_processing_history'),
    )


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    github_username = Column(String(255), unique=True, nullable=False)
    github_id = Column(Integer, unique=True, nullable=False)
    email = Column(String(255), nullable=True)
    avatar_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    # Relationships
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    feedback = relationship("UserFeedback", back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = 'user_sessions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False)
    github_access_token = Column(Text, nullable=True)  # Encrypted in application
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="sessions")


class UserFeedback(Base):
    __tablename__ = 'user_feedback'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    snippet_id = Column(Integer, ForeignKey('snippets.id', ondelete='CASCADE'), nullable=True)
    page_id = Column(Integer, ForeignKey('pages.id', ondelete='CASCADE'), nullable=True)
    rating = Column(Boolean, nullable=False)  # True = thumbs_up, False = thumbs_down
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="feedback")
    snippet = relationship("Snippet", back_populates="feedback")
    page = relationship("Page", back_populates="feedback")
    
    # Constraints
    __table_args__ = (
        sa.CheckConstraint("(snippet_id IS NOT NULL AND page_id IS NULL) OR (snippet_id IS NULL AND page_id IS NOT NULL)", name='check_feedback_target'),
    )