from fastapi import APIRouter, Request, Body, Query, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from shared.utils.database import SessionLocal, get_db
from shared.models import Page, User, UserFeedback, Snippet, RewrittenDocument
from shared.config import config, get_repo_from_url, AZURE_DOCS_REPOS
from sqlalchemy import func
from packages.scorer.llm_client import LLMClient
from jinja_env import templates
import os
import time
import re
import httpx
import urllib.parse
import json as pyjson
import logging
import hashlib
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from shared.utils.date_utils import get_current_date_mmddyyyy, update_ms_date_in_content

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory cache for updated markdown (keyed by page_id)
UPDATED_MARKDOWN_CACHE = {}
CACHE_TTL_SECONDS = 24 * 3600  # 24 hours

def extract_yaml_header(md: str):
    import re, yaml
    if md.startswith('---'):
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', md, re.DOTALL)
        if match:
            yaml_str = match.group(1)
            md_body = match.group(2)
            try:
                yaml_dict = yaml.safe_load(yaml_str)
            except Exception:
                yaml_dict = None
            return yaml_dict, yaml_str, md_body
    return None, None, md


def create_content_hash(content: str) -> str:
    """Create SHA256 hash of content for deduplication"""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def get_github_raw_url_for_page(page_url: str) -> tuple[str | None, str | None, str | None]:
    """
    Get the raw GitHub URL and repo path for a page.

    Args:
        page_url: The page URL (GitHub or MS Learn)

    Returns:
        Tuple of (github_raw_url, repo_path, repo_full_name) or (None, None, None) if not found
    """
    parsed = urllib.parse.urlparse(page_url)
    path = parsed.path

    if 'github.com' in parsed.netloc and '/blob/' in path:
        # GitHub URL - extract repo path after /blob/{branch}/
        repo_path = re.split(r'/blob/[^/]+/', path, maxsplit=1)[-1]
        repo = get_repo_from_url(page_url)
        if repo:
            github_raw_url = repo.get_raw_url(repo_path)
            return github_raw_url, repo_path, repo.full_name
        # Fallback for unknown repos
        return None, repo_path, None

    elif 'learn.microsoft.com' in parsed.netloc:
        # MS Learn URL - convert to GitHub path
        # For MS Learn, we need to determine which repo to use
        # Default to first repo since all repos publish to the same MS Learn namespace
        path = re.sub(r'^/(en-us/)?azure/', '', path).rstrip('/')
        if not path.endswith('.md'):
            path += '.md'
        repo_path = f"articles/{path}"

        # Default to first repo (azure-docs-pr) for MS Learn URLs
        # since we can't determine which repo from the MS Learn URL alone
        default_repo = AZURE_DOCS_REPOS[0] if AZURE_DOCS_REPOS else None
        if default_repo:
            github_raw_url = default_repo.get_raw_url(repo_path)
            return github_raw_url, repo_path, default_repo.full_name

    return None, None, None


def store_rewritten_document(page_id: int, content: str, yaml_header: dict = None, 
                           generation_params: dict = None) -> int:
    """Store rewritten document in database, return document ID. Handle deduplication via content hash."""
    content_hash = create_content_hash(content)
    
    db = SessionLocal()
    try:
        # Check if identical content already exists for this page
        existing_doc = db.query(RewrittenDocument).filter(
            RewrittenDocument.page_id == page_id,
            RewrittenDocument.content_hash == content_hash
        ).first()
        
        if existing_doc:
            logger.info(f"Reusing existing rewritten document {existing_doc.id} for page {page_id} (content hash: {content_hash[:12]}...)")
            return existing_doc.id
        
        # Create new document version
        new_doc = RewrittenDocument(
            page_id=page_id,
            content=content,
            content_hash=content_hash,
            yaml_header=yaml_header,
            generation_params=generation_params or {}
        )
        
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
        
        logger.info(f"Created new rewritten document {new_doc.id} for page {page_id} (content hash: {content_hash[:12]}...)")
        return new_doc.id
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to store rewritten document for page {page_id}: {e}")
        raise
    finally:
        db.close()

@router.get("/proposed_change", response_class=HTMLResponse)
async def proposed_change(request: Request, page_id: int = Query(...)):
    db = SessionLocal()
    page = db.query(Page).filter(Page.id == page_id).first()
    db.close()
    if not page:
        return HTMLResponse("<h2>Page not found</h2>", status_code=404)
    mcp_holistic = page.mcp_holistic or {}
    if isinstance(mcp_holistic, str):
        try:
            mcp_holistic = pyjson.loads(mcp_holistic)
        except Exception:
            mcp_holistic = {}
    recommendations = mcp_holistic.get('recommendations', [])

    # Get raw GitHub URL using config-based helper
    github_raw_url, repo_path, repo_full_name = get_github_raw_url_for_page(page.url)

    if github_raw_url:
        logger.info(f"Fetching markdown from GitHub: {github_raw_url}")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(github_raw_url)
                if resp.status_code == 200:
                    original_markdown = resp.text
                    logger.info(f"Successfully fetched {len(resp.text)} bytes from GitHub")
                else:
                    original_markdown = f"[Could not fetch markdown from GitHub: {github_raw_url} (HTTP {resp.status_code})]"
                    logger.warning(f"GitHub fetch failed with status {resp.status_code}")
        except httpx.TimeoutException:
            original_markdown = f"[Timeout fetching markdown from GitHub: {github_raw_url}]"
            logger.error(f"Timeout fetching from GitHub after 30 seconds: {github_raw_url}")
        except Exception as e:
            original_markdown = f"[Error fetching markdown from GitHub: {github_raw_url} - {str(e)}]"
            logger.error(f"Error fetching from GitHub: {e}")
    else:
        original_markdown = f"[Unrecognized URL format: {page.url}]"
    yaml_dict_orig, yaml_str_orig, md_body_orig = extract_yaml_header(original_markdown)
    original_markdown_content = original_markdown  # Keep full original markdown with YAML header
    
    # Construct GitHub blob URL and MS Learn URL for template
    github_url = None
    mslearn_url = None

    if repo_path and repo_full_name:
        # Construct GitHub blob URL using the detected repo
        repo = get_repo_from_url(page.url)
        branch = repo.branch if repo else "main"
        github_url = f"https://github.com/{repo_full_name}/blob/{branch}/{repo_path}"

        # Construct MS Learn URL from repo path (same for all repos)
        if repo_path.startswith('articles/'):
            article_path = repo_path[9:]  # Remove 'articles/' prefix
            if article_path.endswith('.md'):
                article_path = article_path[:-3]  # Remove .md extension
            mslearn_url = f"https://learn.microsoft.com/en-us/azure/{article_path}"

    # If original page URL is already MS Learn, use that
    if 'learn.microsoft.com' in page.url:
        mslearn_url = page.url
    
    file_path_for_template = repo_path or "unknown-file.md"
    logger.info(f"Proposed change page for page_id={page_id}: file_path='{file_path_for_template}', original_url='{page.url}'")
    
    return templates.TemplateResponse("proposed_change.html", {
        "request": request,
        "original_markdown": original_markdown_content,
        "yaml_header_orig": yaml_dict_orig,
        "yaml_header_str_orig": yaml_str_orig,
        "debug_info": {},
        "file_path": file_path_for_template,
        "github_url": github_url,
        "mslearn_url": mslearn_url,
    })

@router.get("/generate_updated_markdown")
async def generate_updated_markdown(page_id: int = Query(...), force: bool = Query(False)):
    now = time.time()
    cache_entry = UPDATED_MARKDOWN_CACHE.get(page_id)
    debug_log = []
    if cache_entry and not force:
        updated_markdown, debug_info, ts = cache_entry
        debug_log.append(f"Cache hit for page_id={page_id}, age={now-ts:.1f}s")
        if now - ts < CACHE_TTL_SECONDS:
            debug_info = debug_info or {}
            debug_info['debug_log'] = debug_log
            # Extract body for cached response
            _, _, cached_md_body = extract_yaml_header(updated_markdown)
            return JSONResponse({
                "updated_markdown": updated_markdown,
                "updated_markdown_body": cached_md_body,
                "debug_info": debug_info,
                "cached": True,
                "rewritten_document_id": debug_info.get('rewritten_document_id')
            })
        else:
            debug_log.append(f"Cache expired for page_id={page_id}, age={now-ts:.1f}s")
    else:
        if not cache_entry:
            debug_log.append(f"Cache miss for page_id={page_id}")
        elif force:
            debug_log.append(f"Force refresh for page_id={page_id}")
    db = SessionLocal()
    page = db.query(Page).filter(Page.id == page_id).first()
    db.close()
    if not page:
        return JSONResponse({"error": "Page not found"}, status_code=404)
    mcp_holistic = page.mcp_holistic or {}
    if isinstance(mcp_holistic, str):
        try:
            mcp_holistic = pyjson.loads(mcp_holistic)
        except Exception:
            mcp_holistic = {}
    recommendations = mcp_holistic.get('recommendations', [])

    # Get raw GitHub URL using config-based helper
    github_raw_url, repo_path, repo_full_name = get_github_raw_url_for_page(page.url)

    if github_raw_url:
        logger.info(f"Fetching markdown from GitHub for update: {github_raw_url}")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(github_raw_url)
                if resp.status_code == 200:
                    original_markdown = resp.text
                    logger.info(f"Successfully fetched {len(resp.text)} bytes from GitHub for update")
                else:
                    original_markdown = f"[Could not fetch markdown from GitHub: {github_raw_url} (HTTP {resp.status_code})]"
                    logger.warning(f"GitHub fetch failed with status {resp.status_code} for update")
        except httpx.TimeoutException:
            original_markdown = f"[Timeout fetching markdown from GitHub: {github_raw_url}]"
            logger.error(f"Timeout fetching from GitHub after 30 seconds for update: {github_raw_url}")
        except Exception as e:
            original_markdown = f"[Error fetching markdown from GitHub: {github_raw_url} - {str(e)}]"
            logger.error(f"Error fetching from GitHub for update: {e}")
    else:
        original_markdown = f"[Unrecognized URL format: {page.url}]"
    try:
        llm = LLMClient()
        debug_info = {}
        debug_info['llm_api_available'] = llm.api_available
    except Exception as e:
        logger.error(f"Failed to initialize LLMClient: {e}")
        return JSONResponse({"error": f"Failed to initialize LLM client: {str(e)}"}, status_code=500)
    debug_info['recommendations'] = recommendations
    debug_info['llm_prompt'] = None
    debug_info['llm_response'] = None
    mcp_holistic = mcp_holistic or {}
    if not isinstance(mcp_holistic, dict):
        mcp_holistic = {}
    debug_info['mcp_holistic'] = mcp_holistic
    if not llm.api_available:
        updated_markdown = original_markdown
        debug_log.append('LLM not available, using original markdown.')
        debug_info['llm_status'] = 'LLM not available, using original markdown.'
    elif not recommendations:
        updated_markdown = original_markdown
        debug_log.append('No recommendations provided, using original markdown.')
        debug_info['llm_status'] = 'No recommendations provided, using original markdown.'
    else:
        prompt = f"""
You are an expert technical writer. Given the following original markdown and a set of recommendations, rewrite the markdown to address the recommendations. Output the complete Markdown file contents, ready for direct replacement. All unchanged content must be included in full. Maintain correct Markdown syntax and Azure style guide consistency. \n\nOriginal Markdown:\n{original_markdown}\n\nRecommendations:\n{recommendations}\n\nUpdated Markdown:"""
        logger.info(f"Calling LLM with {len(prompt)} character prompt")
        debug_info['llm_prompt'] = prompt
        try:
            response = llm.client.chat.completions.create(
                model=llm.deployment,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
                temperature=0.3
            )
            updated_markdown = response.choices[0].message.content.strip()
            debug_info['llm_response'] = updated_markdown
            debug_log.append('LLM call succeeded.')
            debug_info['llm_status'] = 'LLM call succeeded.'
        except Exception as e:
            updated_markdown = original_markdown
            debug_log.append(f'LLM call failed: {e}')
            debug_info['llm_status'] = f'LLM call failed: {e}'
    yaml_dict, yaml_str, md_body = extract_yaml_header(updated_markdown)
    if yaml_str:
        updated_markdown_content = f"---\n{yaml_str}\n---\n{md_body}"
    else:
        updated_markdown_content = md_body
    
    # Store the rewritten document in database for versioning and feedback
    try:
        generation_params = {
            'force_refresh': force,
            'recommendations_count': len(recommendations),
            'llm_available': llm.api_available,
            'generated_at': datetime.utcnow().isoformat()
        }
        
        document_id = store_rewritten_document(
            page_id=page_id,
            content=updated_markdown_content,
            yaml_header=yaml_dict,
            generation_params=generation_params
        )
        debug_info['rewritten_document_id'] = document_id
        
    except Exception as e:
        logger.error(f"Failed to store rewritten document: {e}")
        # Continue without failing the request
        debug_info['storage_error'] = str(e)
    
    # Keep in-memory cache for performance (but database is source of truth)
    UPDATED_MARKDOWN_CACHE[page_id] = (updated_markdown_content, debug_info, now)
    debug_info['debug_log'] = debug_log
    
    return JSONResponse({
        "updated_markdown": updated_markdown_content,
        "updated_markdown_body": md_body,
        "yaml_header": yaml_dict,
        "yaml_header_str": yaml_str,
        "debug_info": debug_info,
        "cached": False,
        "rewritten_document_id": debug_info.get('rewritten_document_id')
    })

@router.post("/api/compute_diff")
async def compute_diff(
    request: Request,
    body: dict = Body(...)
):
    """Compute unified diff between original and updated markdown"""
    try:
        original = body.get('original', '')
        updated = body.get('updated', '')
        context_lines = body.get('context_lines', 3)
        
        if not original or not updated:
            return JSONResponse({"error": "Missing original or updated content"}, status_code=400)
        
        import difflib
        
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile='original.md',
            tofile='updated.md',
            n=context_lines
        )
        
        diff_text = ''.join(diff)
        
        # Count additions and deletions
        additions = 0
        deletions = 0
        for line in diff_text.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                additions += 1
            elif line.startswith('-') and not line.startswith('---'):
                deletions += 1
        
        return JSONResponse({
            "diff": diff_text,
            "additions": additions,
            "deletions": deletions
        })
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/score_page_holistic")
async def score_page_holistic(request: Request, body: dict = Body(...)):
    mcp_url = os.getenv("MCP_SERVER_URL", "http://localhost:9000/score_page")
    page_content = body.get("page_content")
    metadata = body.get("metadata", {})
    if not page_content:
        return JSONResponse({"error": "Missing page_content"}, status_code=400)
    try:
        logger.info(f"Calling MCP server at {mcp_url}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(mcp_url, json={"page_content": page_content, "metadata": metadata})
            if resp.status_code == 200:
                return JSONResponse(resp.json())
            else:
                return JSONResponse({"error": f"MCP server error: {resp.status_code} {resp.text}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"Exception contacting MCP server: {e}"}, status_code=500)

@router.post("/suggest_linux_pr")
async def suggest_linux_pr(request: Request, body: dict = Body(...)):
    url = body.get('url')
    if not url:
        return JSONResponse({"error": "Missing URL"}, status_code=400)
    doc_content = None
    try:
        if 'github.com' in url and '/blob/' in url:
            raw_url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
            resp = httpx.get(raw_url)
            if resp.status_code == 200:
                doc_content = resp.text
        else:
            resp = httpx.get(url)
            if resp.status_code == 200:
                doc_content = resp.text
    except Exception:
        pass
    if not doc_content:
        return JSONResponse({"error": "Failed to fetch document content."}, status_code=500)
    frontmatter_match = re.match(r'(?s)^---\n(.*?)\n---\n(.*)', doc_content)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        markdown_body = frontmatter_match.group(2)
        processed_content = f"# The following is the full markdown page (YAML frontmatter moved to end):\n\n{markdown_body}\n\n---\n{frontmatter}\n---"
    else:
        processed_content = f"# The following is the full markdown page:\n\n{doc_content}"
    prompt = (
        "You are an expert in cross-platform technical documentation.\n"
        "\n"
        "TASK: Rewrite the following documentation page to make it Linux-first.\n"
        "- Add or improve Linux/az CLI/bash examples.\n"
        "- Clarify platform-specific instructions.\n"
        "- Ensure parity between Windows and Linux instructions.\n"
        "- DO NOT provide any advice, explanation, or summary.\n"
        "- DO NOT output anything except the full revised page in markdown.\n"
        "- DO NOT output analysis or meta-comments.\n"
        "- Output ONLY the full revised page, wrapped in triple backticks (```).\n"
        "\n"
        "EXAMPLE:\n"
        "Original:\n"
        "---\n"
        "title: 'Create a resource group'\n"
        f"ms.date: {get_current_date_mmddyyyy()}\n"
        "---\n"
        "\n"
        "# Create a resource group (PowerShell)\n"
        "$rg = New-AzResourceGroup -Name 'myResourceGroup' -Location 'eastus'\n"
        "\n"
        "Revised:\n"
        "```\n"
        "---\n"
        "title: 'Create a resource group'\n"
        f"ms.date: {get_current_date_mmddyyyy()}\n"
        "---\n"
        "\n"
        "# Create a resource group (PowerShell)\n"
        "$rg = New-AzResourceGroup -Name 'myResourceGroup' -Location 'eastus'\n"
        "\n"
        "# Create a resource group (Azure CLI)\n"
        "az group create --name myResourceGroup --location eastus\n"
        "```\n"
        "\n"
        "Now, here is the page to revise:\n"
        f"{processed_content}"
    )
    llm = LLMClient()
    try:
        suggestion = llm.score_snippet({'code': prompt, 'context': ''})
        raw_response = suggestion.get('suggested_linux_alternative') or suggestion.get('explanation') or str(suggestion)
        match = re.search(r'```(?:markdown)?\n([\s\S]+?)```', raw_response)
        if match:
            proposed = match.group(1).strip()
        else:
            proposed = raw_response
        
        # Ensure the ms.date field is updated to current date in the proposed content
        proposed = update_ms_date_in_content(proposed)
        
    except Exception as e:
        proposed = f"Error generating suggestion: {e}"
    return JSONResponse({"original": doc_content, "proposed": proposed})

def get_priority_label_and_score(mcp_holistic):
    if not mcp_holistic:
        return ("Low", 1)
    bias_types = mcp_holistic.get('bias_types')
    if isinstance(bias_types, str):
        bias_types = [bias_types]
    if not bias_types or not isinstance(bias_types, list):
        return ("Low", 1)
    n_bias = len(bias_types)
    if n_bias >= 3:
        return ("High", 3)
    elif n_bias == 2:
        return ("Medium", 2)
    elif n_bias == 1:
        return ("Low", 1)
    else:
        return ("Low", 1)


# Import auth dependencies at the end to avoid circular imports
from routes.auth import get_current_user
from shared.infrastructure.github_pr_service import GitHubPRService
from shared.infrastructure.github_app_service import github_app_service
from utils.session import get_session_storage


class CreatePRRequest(BaseModel):
    """Request model for creating a GitHub PR"""
    file_path: str
    new_content: str
    title: str
    body: str
    base_branch: str = "main"
    source_repo: Optional[str] = None  # e.g., "MicrosoftDocs/azure-docs-pr" - if not provided, defaults to first repo


@router.post("/api/create_github_pr")
async def create_github_pr(
    request: Request,
    pr_request: CreatePRRequest,
    current_user: Optional[User] = Depends(get_current_user)
):
    """Create a GitHub PR from the authenticated user's account"""
    if not current_user:
        raise HTTPException(401, "Authentication required")
    
    # Get user's GitHub token from session
    session_token = request.cookies.get("session_token")
    session_storage = get_session_storage()
    session_data = session_storage.get(session_token)
    
    if not session_data or "github_token" not in session_data:
        raise HTTPException(401, "GitHub token not found in session")
    
    github_token = session_data["github_token"]
    
    try:
        logger.info(f"Creating GitHub PR for user {current_user.github_username}: file_path='{pr_request.file_path}', title='{pr_request.title}'")

        # Try GitHub App first, fallback to OAuth
        pr_service = GitHubPRService(
            access_token=github_token,
            username=current_user.github_username
        )

        # Determine which repo to target
        # Use provided source_repo, or default to first configured repo
        if pr_request.source_repo:
            source_repo = pr_request.source_repo
            # Find matching repo config for public fallback
            matching_repo = None
            for repo in AZURE_DOCS_REPOS:
                if repo.full_name.lower() == source_repo.lower() or repo.public_full_name.lower() == source_repo.lower():
                    matching_repo = repo
                    break
            public_fallback = matching_repo.public_full_name if matching_repo else source_repo.replace("-pr", "")
        else:
            # Default to first repo (azure-docs-pr)
            default_repo = AZURE_DOCS_REPOS[0] if AZURE_DOCS_REPOS else None
            source_repo = default_repo.full_name if default_repo else "microsoftdocs/azure-docs-pr"
            public_fallback = default_repo.public_full_name if default_repo else "microsoftdocs/azure-docs"

        logger.info(f"Using source repo: {source_repo}")

        try:
            # Create the pull request (will fork source repo, make changes, and create PR back to source)
            pr_url = await pr_service.create_pr_from_user_account(
                source_repo=source_repo,
                file_path=pr_request.file_path,
                new_content=pr_request.new_content,
                pr_title=pr_request.title,
                pr_body=pr_request.body,
                base_branch=pr_request.base_branch
            )
        except Exception as e:
            # If we get organization access restrictions, try public repo
            if "OAuth App access restrictions" in str(e) or "403" in str(e):
                logger.warning(f"Private repo access restricted, falling back to public repo: {e}")
                source_repo = public_fallback
                pr_url = await pr_service.create_pr_from_user_account(
                    source_repo=source_repo,
                    file_path=pr_request.file_path,
                    new_content=pr_request.new_content,
                    pr_title=pr_request.title,
                    pr_body=pr_request.body,
                    base_branch=pr_request.base_branch
                )
            else:
                raise  # Re-raise if it's not an access restriction error
        
        return JSONResponse({
            "success": True,
            "pr_url": pr_url,
            "message": "Pull request created successfully"
        })
        
    except Exception as e:
        logger.error(f"Failed to create PR: {str(e)}")
        
        # Provide user-friendly error messages
        error_message = str(e)
        if "403" in error_message or "permission" in error_message.lower():
            if "OAuth App access restrictions" in error_message:
                error_message = "Please install the GitHub App to access private repositories. Contact your administrator for the installation link."
            else:
                error_message = "Permission denied. Please ensure you have access to create pull requests."
        elif "404" in error_message:
            error_message = "Repository not found. Please check the repository name."
        elif "rate limit" in error_message.lower():
            error_message = "GitHub API rate limit exceeded. Please try again later."
        
        return JSONResponse({
            "success": False,
            "error": error_message,
            "error_code": "PR_CREATION_FAILED"
        }, status_code=400)


@router.get("/api/github_app_status")
async def github_app_status(
    current_user: Optional[User] = Depends(get_current_user)
):
    """Check GitHub App installation status for the current user"""
    if not current_user:
        return JSONResponse({
            "app_configured": False,
            "user_has_installation": False,
            "installation_url": None,
            "username": None
        })
    
    # Get detailed status for debugging
    has_installation = github_app_service.is_user_installation_available(current_user.github_username)
    
    return JSONResponse({
        "app_configured": github_app_service.configured,
        "user_has_installation": has_installation,
        "installation_url": github_app_service.get_installation_url(),
        "username": current_user.github_username,
        "app_id": config.github_app.app_id,
        "private_key_configured": bool(config.github_app.private_key)
    })


class FeedbackRequest(BaseModel):
    """Request model for user feedback"""
    snippet_id: int
    rating: str  # 'thumbs_up' or 'thumbs_down'
    comment: Optional[str] = None


@router.post("/api/feedback/rate")
async def rate_snippet(
    feedback: FeedbackRequest,
    current_user: Optional[User] = Depends(get_current_user),
    db: SessionLocal = Depends(get_db)
):
    """Submit user feedback on a snippet"""
    if not current_user:
        raise HTTPException(401, "Authentication required")
    
    # Validate rating
    if feedback.rating not in ['thumbs_up', 'thumbs_down']:
        raise HTTPException(400, "Invalid rating. Must be 'thumbs_up' or 'thumbs_down'")
    
    # Check if snippet exists
    snippet = db.query(Snippet).filter(Snippet.id == feedback.snippet_id).first()
    if not snippet:
        raise HTTPException(404, "Snippet not found")
    
    # Check if user already provided feedback
    existing_feedback = db.query(UserFeedback).filter(
        UserFeedback.user_id == current_user.id,
        UserFeedback.snippet_id == feedback.snippet_id
    ).first()
    
    if existing_feedback:
        # Update existing feedback
        existing_feedback.rating = feedback.rating
        existing_feedback.comment = feedback.comment
        existing_feedback.created_at = datetime.utcnow()
    else:
        # Create new feedback
        new_feedback = UserFeedback(
            user_id=current_user.id,
            snippet_id=feedback.snippet_id,
            rating=feedback.rating,
            comment=feedback.comment
        )
        db.add(new_feedback)
    
    db.commit()
    
    # Get updated feedback counts
    feedback_counts = db.query(
        UserFeedback.rating,
        func.count(UserFeedback.id)
    ).filter(
        UserFeedback.snippet_id == feedback.snippet_id
    ).group_by(UserFeedback.rating).all()
    
    counts = {
        "thumbs_up": 0,
        "thumbs_down": 0
    }
    for rating, count in feedback_counts:
        counts[rating] = count
    
    return JSONResponse({
        "success": True,
        "message": "Feedback submitted successfully",
        "feedback_counts": counts
    })


@router.get("/api/feedback/stats/{snippet_id}")
async def get_feedback_stats(
    snippet_id: int,
    db: SessionLocal = Depends(get_db)
):
    """Get feedback statistics for a snippet"""
    # Check if snippet exists
    snippet = db.query(Snippet).filter(Snippet.id == snippet_id).first()
    if not snippet:
        raise HTTPException(404, "Snippet not found")
    
    # Get feedback counts
    feedback_counts = db.query(
        UserFeedback.rating,
        func.count(UserFeedback.id)
    ).filter(
        UserFeedback.snippet_id == snippet_id
    ).group_by(UserFeedback.rating).all()
    
    counts = {
        "thumbs_up": 0,
        "thumbs_down": 0
    }
    for rating, count in feedback_counts:
        counts[rating] = count
    
    # Get recent comments
    recent_feedback = db.query(UserFeedback).filter(
        UserFeedback.snippet_id == snippet_id,
        UserFeedback.comment.isnot(None)
    ).order_by(UserFeedback.created_at.desc()).limit(5).all()
    
    comments = [
        {
            "user": feedback.user.github_username,
            "rating": feedback.rating,
            "comment": feedback.comment,
            "created_at": feedback.created_at.isoformat() if hasattr(feedback.created_at, 'isoformat') else str(feedback.created_at)
        }
        for feedback in recent_feedback
    ]
    
    return JSONResponse({
        "snippet_id": snippet_id,
        "feedback_counts": counts,
        "recent_comments": comments
    })
