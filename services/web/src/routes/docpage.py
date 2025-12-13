from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from shared.utils.database import SessionLocal
from shared.models import Scan, Page, Snippet, User
from shared.utils.bias_utils import is_page_biased
from shared.config import AZURE_DOCS_REPOS, get_repo_from_url
from routes.auth import get_current_user
from typing import Optional
import os
import json
import re
from urllib.parse import urlparse
from datetime import datetime

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "../templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def get_github_url(page_url: str) -> str:
    """Convert a page URL (GitHub or MS Learn) to GitHub format."""
    parsed = urlparse(page_url)

    if 'github.com' in parsed.netloc:
        # Already a GitHub URL - preserve it as-is
        return page_url
    elif 'learn.microsoft.com' in parsed.netloc:
        # Convert MS Learn URL to GitHub
        path = parsed.path
        # Remove locale prefix and azure prefix
        path = re.sub(r'^/(en-us/)?azure/', '', path).rstrip('/')

        # Add .md extension if not present
        if not path.endswith('.md'):
            path += '.md'

        # Use first configured repo as default (can't determine repo from MS Learn URL)
        default_repo = AZURE_DOCS_REPOS[0] if AZURE_DOCS_REPOS and len(AZURE_DOCS_REPOS) > 0 else None
        if default_repo:
            github_url = f"https://github.com/{default_repo.full_name}/blob/{default_repo.branch}/{default_repo.articles_path}/{path}"
        else:
            # Fallback if no repos configured
            github_url = f"https://github.com/MicrosoftDocs/azure-docs-pr/blob/main/articles/{path}"
        return github_url
    else:
        # Unknown format, return original
        return page_url


def get_mslearn_url(page_url: str) -> str:
    """Convert a page URL (GitHub or MS Learn) to MS Learn format."""
    parsed = urlparse(page_url)

    if 'learn.microsoft.com' in parsed.netloc:
        # Already an MS Learn URL
        return page_url
    elif 'github.com' in parsed.netloc and '/blob/' in parsed.path:
        # Convert GitHub URL to MS Learn
        # Extract path after /blob/{branch}/
        repo_path = re.split(r'/blob/[^/]+/', parsed.path, maxsplit=1)[-1]

        # Remove articles/ prefix and .md extension
        if repo_path.startswith('articles/'):
            repo_path = repo_path[9:]  # Remove 'articles/'

        if repo_path.endswith('.md'):
            repo_path = repo_path[:-3]  # Remove '.md'

        # Build MS Learn URL (same for all repos)
        mslearn_url = f"https://learn.microsoft.com/en-us/azure/{repo_path}"
        return mslearn_url
    else:
        # Unknown format, return original
        return page_url


def get_page_scan_history(db, page_url: str):
    """Get scan history for a specific page URL across all scans."""
    # Get all scans ordered by date
    scans = db.query(Scan).order_by(Scan.started_at.desc()).all()
    
    history = []
    for scan in scans:
        # Find this page in the scan
        page = db.query(Page).filter(
            Page.scan_id == scan.id,
            Page.url == page_url
        ).first()
        
        if page:
            # Check if page was biased in this scan
            was_biased = is_page_biased(page)
            
            history.append({
                'scan_id': scan.id,
                'scan_date': scan.started_at,
                'scan_status': scan.status,
                'was_biased': was_biased,
                'page_id': page.id  # Include page ID for that specific scan
            })
    
    return history


def generate_page_summary(page_title: str, page_url: str) -> str:
    """Generate a brief summary of what the page documents based on its title and URL."""
    # Extract key information from URL path
    parsed = urlparse(page_url)
    path_parts = parsed.path.strip('/').split('/')
    
    # Try to identify the service and topic from the URL
    service = None
    topic = None
    
    if 'azure' in path_parts:
        azure_index = path_parts.index('azure')
        if azure_index + 1 < len(path_parts):
            service = path_parts[azure_index + 1].replace('-', ' ').title()
            if azure_index + 2 < len(path_parts):
                topic = ' '.join(path_parts[azure_index + 2:]).replace('-', ' ')
    
    # Generate summary based on available information
    if service and topic:
        summary = f"This page documents {topic} for Azure {service}. "
    elif service:
        summary = f"This page provides documentation for Azure {service}. "
    else:
        summary = "This page is part of the Azure documentation. "
    
    # Add generic second sentence
    summary += "It contains code examples and configuration instructions for working with Azure services."
    
    return summary


@router.get("/docpage/{page_id}")
async def docpage_details(
    page_id: int, 
    request: Request, 
    current_user: Optional[User] = Depends(get_current_user)
):
    """Show detailed information for a specific documentation page."""
    db = SessionLocal()
    
    try:
        # Get the page by ID
        page = db.query(Page).filter(Page.id == page_id).first()
        
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        
        # Extract page title from URL (last part without extension)
        page_title = page.url.split('/')[-1].replace('.md', '').replace('-', ' ').title()
        
        # Generate URLs
        github_url = get_github_url(page.url)
        mslearn_url = get_mslearn_url(page.url)
        
        # Generate page summary
        page_summary = generate_page_summary(page_title, page.url)
        
        # Check if page is currently biased
        is_biased = is_page_biased(page)
        
        # Parse mcp_holistic if it's a string
        mcp_holistic = page.mcp_holistic
        if isinstance(mcp_holistic, str):
            try:
                mcp_holistic = json.loads(mcp_holistic)
            except Exception:
                mcp_holistic = None
        
        # Get bias details if page is biased
        bias_summary = None
        bias_recommendations = []
        bias_types = []
        
        if is_biased and mcp_holistic:
            bias_summary = mcp_holistic.get('summary', '')
            bias_recommendations = mcp_holistic.get('recommendations', [])
            bias_types = mcp_holistic.get('bias_types', [])
        
        # Get all snippets for this page
        snippets = db.query(Snippet).filter(Snippet.page_id == page.id).all()
        
        # Get scan history for this page URL
        scan_history = get_page_scan_history(db, page.url)
        
        # Get the scan information for this page
        scan = db.query(Scan).filter(Scan.id == page.scan_id).first()
        
        return templates.TemplateResponse("docpage_details.html", {
            "request": request,
            "page": page,
            "page_title": page_title,
            "page_summary": page_summary,
            "github_url": github_url,
            "mslearn_url": mslearn_url,
            "is_biased": is_biased,
            "bias_summary": bias_summary,
            "bias_recommendations": bias_recommendations,
            "bias_types": bias_types,
            "snippets": snippets,
            "scan_history": scan_history,
            "scan": scan,
            "user": current_user,
            "mcp_holistic": mcp_holistic  # Pass full object for PR functionality
        })
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Exception in docpage_details: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
        
    finally:
        db.close()