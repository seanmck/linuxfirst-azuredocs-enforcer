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
    pages = relationship("Page", back_populates="scan")

class Page(Base):
    __tablename__ = 'pages'
    id = Column(Integer, primary_key=True)
    scan_id = Column(Integer, ForeignKey('scans.id'))
    url = Column(String)
    status = Column(String)
    mcp_holistic = Column(JSON)  # Holistic MCP result per page
    scan = relationship("Scan", back_populates="pages")
    snippets = relationship("Snippet", back_populates="page")

class Snippet(Base):
    __tablename__ = 'snippets'
    id = Column(Integer, primary_key=True)
    page_id = Column(Integer, ForeignKey('pages.id'))
    context = Column(Text)
    code = Column(Text)
    llm_score = Column(JSON)
    page = relationship("Page", back_populates="snippets")
