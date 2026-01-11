"""
Shared pytest fixtures for all tests.
"""
import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.models import Base, Scan, Page, Snippet


@pytest.fixture
def db_engine():
    """Create an in-memory SQLite database engine for tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Create a database session for tests."""
    with Session(db_engine) as session:
        yield session


@pytest.fixture
def sample_scan(db_session):
    """Create a sample scan for testing."""
    scan = Scan(
        url="https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/storage/overview.md",
        status="in_progress",
        current_phase="discovery",
    )
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)
    return scan


@pytest.fixture
def sample_page(db_session, sample_scan):
    """Create a sample page for testing."""
    page = Page(
        scan_id=sample_scan.id,
        url="https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/storage/overview.md",
        status="completed",
        mcp_holistic={"bias_types": ["powershell_only"], "summary": "Uses PowerShell only"},
        doc_set="storage",
    )
    db_session.add(page)
    db_session.commit()
    db_session.refresh(page)
    return page


@pytest.fixture
def sample_snippet(db_session, sample_page):
    """Create a sample snippet for testing."""
    snippet = Snippet(
        page_id=sample_page.id,
        context="Install Azure CLI",
        code="Install-Module -Name Az -Scope CurrentUser",
        llm_score={"is_biased": True, "bias_type": "powershell_only"},
    )
    db_session.add(snippet)
    db_session.commit()
    db_session.refresh(snippet)
    return snippet


@pytest.fixture
def mock_page_with_bias():
    """Create a mock page object with bias data."""
    page = MagicMock()
    page.mcp_holistic = {
        "bias_types": ["powershell_only", "windows_paths"],
        "summary": "Uses PowerShell and Windows paths",
        "recommendations": ["Add bash alternatives"]
    }
    return page


@pytest.fixture
def mock_page_without_bias():
    """Create a mock page object without bias data."""
    page = MagicMock()
    page.mcp_holistic = {
        "bias_types": [],
        "summary": "Cross-platform documentation"
    }
    return page


@pytest.fixture
def mock_page_no_mcp():
    """Create a mock page object with no MCP data."""
    page = MagicMock()
    page.mcp_holistic = None
    return page


@pytest.fixture
def sample_html_with_code():
    """Sample HTML content with code blocks."""
    return """
    <html>
    <body>
        <section>
            <h2>Install Azure CLI</h2>
            <p>Run the following command:</p>
            <pre>Install-Module -Name Az -Scope CurrentUser</pre>
        </section>
        <section>
            <h2>Linux Installation</h2>
            <p>Use apt-get:</p>
            <pre>sudo apt-get install azure-cli</pre>
        </section>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_with_azure_powershell_tab():
    """Sample HTML with Azure PowerShell tab."""
    return """
    <html>
    <body>
        <div data-tab="azure-powershell">
            <h3>Azure PowerShell</h3>
            <pre>Get-AzResourceGroup</pre>
        </div>
        <div data-tab="azure-cli">
            <h3>Azure CLI</h3>
            <pre>az group list</pre>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_with_windows_header():
    """Sample HTML with Windows-specific header."""
    return """
    <html>
    <body>
        <section>
            <h2>Windows Installation</h2>
            <pre>choco install azure-cli</pre>
        </section>
    </body>
    </html>
    """


@pytest.fixture
def sample_markdown_with_frontmatter():
    """Sample markdown with YAML frontmatter."""
    return """---
title: Azure Storage Overview
ms.date: 01/15/2024
ms.service: storage
---

# Azure Storage Overview

Azure Storage is a cloud storage solution.
"""


@pytest.fixture
def mock_config(monkeypatch):
    """Set up mock environment variables for testing."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("RABBITMQ_HOST", "localhost")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
