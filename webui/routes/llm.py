from fastapi import APIRouter, Request, Body, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from webui.db import SessionLocal
from src.shared.models import Page
from scorer.llm_client import LLMClient
from webui.jinja_env import templates
import os
import time
import re
import httpx
import urllib.parse
import json as pyjson

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
    parsed = urllib.parse.urlparse(page.url)
    path = parsed.path
    github_raw_url = None
    if 'github.com' in parsed.netloc and '/blob/main/' in path:
        repo_path = path.split('/blob/main/', 1)[-1]
        github_raw_url = f"https://raw.githubusercontent.com/microsoftdocs/azure-docs/main/{repo_path}"
    elif 'learn.microsoft.com' in parsed.netloc:
        path = re.sub(r'^/(en-us/)?azure/', '', path).rstrip('/')
        if not path.endswith('.md'):
            path += '.md'
        repo_path = f"articles/{path}"
        github_raw_url = f"https://raw.githubusercontent.com/microsoftdocs/azure-docs/main/{repo_path}"
    if github_raw_url:
        async with httpx.AsyncClient() as client:
            resp = await client.get(github_raw_url)
            if resp.status_code == 200:
                original_markdown = resp.text
            else:
                original_markdown = f"[Could not fetch markdown from GitHub: {github_raw_url} (HTTP {resp.status_code})]"
    else:
        original_markdown = f"[Unrecognized URL format: {page.url}]"
    yaml_dict_orig, yaml_str_orig, md_body_orig = extract_yaml_header(original_markdown)
    original_markdown_content = md_body_orig
    return templates.TemplateResponse("proposed_change.html", {
        "request": request,
        "original_markdown": original_markdown_content,
        "yaml_header_orig": yaml_dict_orig,
        "yaml_header_str_orig": yaml_str_orig,
        "debug_info": {},
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
            return JSONResponse({
                "updated_markdown": updated_markdown,
                "debug_info": debug_info,
                "cached": True
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
    parsed = urllib.parse.urlparse(page.url)
    path = parsed.path
    github_raw_url = None
    if 'github.com' in parsed.netloc and '/blob/main/' in path:
        repo_path = path.split('/blob/main/', 1)[-1]
        github_raw_url = f"https://raw.githubusercontent.com/microsoftdocs/azure-docs/main/{repo_path}"
    elif 'learn.microsoft.com' in parsed.netloc:
        path = re.sub(r'^/(en-us/)?azure/', '', path).rstrip('/')
        if not path.endswith('.md'):
            path += '.md'
        repo_path = f"articles/{path}"
        github_raw_url = f"https://raw.githubusercontent.com/microsoftdocs/azure-docs/main/{repo_path}"
    if github_raw_url:
        async with httpx.AsyncClient() as client:
            resp = await client.get(github_raw_url)
            if resp.status_code == 200:
                original_markdown = resp.text
            else:
                original_markdown = f"[Could not fetch markdown from GitHub: {github_raw_url} (HTTP {resp.status_code})]"
    else:
        original_markdown = f"[Unrecognized URL format: {page.url}]"
    llm = LLMClient()
    debug_info = {}
    debug_info['llm_api_available'] = llm.api_available
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
    UPDATED_MARKDOWN_CACHE[page_id] = (updated_markdown_content, debug_info, now)
    debug_info['debug_log'] = debug_log
    return JSONResponse({
        "updated_markdown": updated_markdown_content,
        "yaml_header": yaml_dict,
        "yaml_header_str": yaml_str,
        "debug_info": debug_info,
        "cached": False
    })

@router.post("/score_page_holistic")
async def score_page_holistic(request: Request, body: dict = Body(...)):
    mcp_url = os.getenv("MCP_SERVER_URL", "http://localhost:8001/score_page")
    page_content = body.get("page_content")
    metadata = body.get("metadata", {})
    if not page_content:
        return JSONResponse({"error": "Missing page_content"}, status_code=400)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(mcp_url, json={"page_content": page_content, "metadata": metadata}, timeout=60)
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
        "ms.date: 01/01/2024\n"
        "---\n"
        "\n"
        "# Create a resource group (PowerShell)\n"
        "$rg = New-AzResourceGroup -Name 'myResourceGroup' -Location 'eastus'\n"
        "\n"
        "Revised:\n"
        "```\n"
        "---\n"
        "title: 'Create a resource group'\n"
        "ms.date: 01/01/2024\n"
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
