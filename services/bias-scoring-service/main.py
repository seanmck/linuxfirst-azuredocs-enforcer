from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import os
import time
import random
import threading
from collections import deque
import openai
from azure.identity import ManagedIdentityCredential

app = FastAPI()

# AOAI config from environment
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-35-turbo")
AZURE_OPENAI_CLIENTID = os.getenv("AZURE_OPENAI_CLIENTID", "")

# Rate limiting configuration
REQUESTS_PER_MINUTE = int(os.getenv("AZURE_OPENAI_RPM", "60"))
MIN_REQUEST_INTERVAL = 60.0 / REQUESTS_PER_MINUTE
request_times = deque(maxlen=REQUESTS_PER_MINUTE)
rate_limit_lock = threading.Lock()


def wait_for_rate_limit():
    """Ensure we don't exceed rate limits by waiting if necessary"""
    with rate_limit_lock:
        now = time.time()

        # Clean up old request times
        while request_times and request_times[0] < now - 60:
            request_times.popleft()

        # If we're at the limit, wait
        if len(request_times) >= REQUESTS_PER_MINUTE:
            oldest_request = request_times[0]
            wait_time = 60 - (now - oldest_request) + 0.1
            if wait_time > 0:
                print(f"[RATE LIMIT] Waiting {wait_time:.1f} seconds")
                time.sleep(wait_time)
                now = time.time()

        # Ensure minimum interval between requests
        if request_times:
            last_request = request_times[-1]
            time_since_last = now - last_request
            if time_since_last < MIN_REQUEST_INTERVAL:
                wait_time = MIN_REQUEST_INTERVAL - time_since_last
                time.sleep(wait_time)
                now = time.time()

        # Record this request
        request_times.append(now)

# Initialize Azure OpenAI client with appropriate authentication
if AZURE_OPENAI_CLIENTID and not AZURE_OPENAI_KEY:
    # Use managed identity authentication (for cloud deployment)
    credential = ManagedIdentityCredential(client_id=AZURE_OPENAI_CLIENTID)
    
    def get_bearer_token_provider():
        return credential.get_token("https://cognitiveservices.azure.com/.default").token
    
    client = openai.AzureOpenAI(
        azure_ad_token_provider=get_bearer_token_provider,
        api_version="2023-05-15",
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    auth_method = "managed_identity"
elif AZURE_OPENAI_KEY:
    # Use API key authentication (for local development)
    client = openai.AzureOpenAI(
        api_key=AZURE_OPENAI_KEY,
        api_version="2023-05-15",
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    auth_method = "api_key"
else:
    client = None
    auth_method = "none"

print(f"[DEBUG] MCP server Azure OpenAI config:")
print(f"  AZURE_OPENAI_ENDPOINT: {AZURE_OPENAI_ENDPOINT}")
print(f"  AZURE_OPENAI_DEPLOYMENT: {AZURE_OPENAI_DEPLOYMENT}")
print(f"  Authentication method: {auth_method}")
if auth_method == "api_key":
    print(f"  AZURE_OPENAI_KEY (masked): {AZURE_OPENAI_KEY[:4]}...{AZURE_OPENAI_KEY[-4:]}")
elif auth_method == "managed_identity":
    print(f"  AZURE_OPENAI_CLIENTID: {AZURE_OPENAI_CLIENTID}")
print(f"  API version: 2023-05-15")

class ScorePageRequest(BaseModel):
    page_content: str
    metadata: dict = {}


class SnippetInput(BaseModel):
    id: int
    code: str
    language: str = ""
    context: str = ""


class ScoreSnippetsRequest(BaseModel):
    snippets: list[SnippetInput]


# Batch size for snippet scoring (configurable via environment)
LLM_BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "5"))

def extract_page_title(content: str) -> str:
    """Extract the page title from markdown content.

    Looks for:
    1. YAML frontmatter 'title:' field
    2. First # heading
    3. First ## heading as fallback
    """
    import re

    if not content:
        return ""

    # Try YAML frontmatter first (between --- markers)
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        title_match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', frontmatter, re.MULTILINE)
        if title_match:
            return title_match.group(1).strip()

    # Try first # heading
    h1_match = re.search(r'^#\s+(.+?)(?:\s*#*)?\s*$', content, re.MULTILINE)
    if h1_match:
        return h1_match.group(1).strip()

    # Try first ## heading as fallback
    h2_match = re.search(r'^##\s+(.+?)(?:\s*#*)?\s*$', content, re.MULTILINE)
    if h2_match:
        return h2_match.group(1).strip()

    return ""


@app.post("/score_page")
async def score_page(req: ScorePageRequest):
    import json
    import re

    # Extract page title from content
    page_title = extract_page_title(req.page_content)

    prompt = f"""
You are an expert in cross-platform documentation analysis.
Analyze the following documentation page for evidence of Windows bias, such as only Windows/Powershell examples being given, Windows tools/patterns being mentioned exclusively or at least before their Linux equivalents. Return a JSON summary with:
- bias_types: list of bias types found (e.g., 'powershell_heavy', 'windows_first', 'missing_linux_example', 'windows_tools')
- summary: a short summary of the bias
- recommendations: suggestions to improve Linux parity
- severity: "high", "medium", "low", or "none" - how significantly the bias impacts Linux/macOS users:
  - "high": Critical sections are Windows-only; Linux users cannot complete the task
  - "medium": Notable bias creating friction, but workarounds exist
  - "low": Minor bias like Windows examples shown first
  - "none": No meaningful bias detected

Page content:
{req.page_content}
"""

    max_retries = 5
    base_delay = 1
    last_error = None

    for attempt in range(max_retries):
        # Wait for rate limit before making request
        wait_for_rate_limit()

        try:
            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=[{"role": "system", "content": "You are a documentation bias analysis assistant."},
                          {"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=512,
                timeout=60,
            )
            # Try to extract JSON from the response
            text = response.choices[0].message.content
            match = re.search(r'\{[\s\S]+\}', text)
            if match:
                result = json.loads(match.group(0))
            else:
                result = {"raw": text, "bias_types": []}
            # Add page title to result
            result["page_title"] = page_title
            return result

        except openai.RateLimitError as rate_error:
            last_error = rate_error
            if attempt < max_retries - 1:
                # Exponential backoff with jitter
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"[RATE LIMIT] 429 received, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                print(f"[ERROR] Rate limit exhausted after {max_retries} retries")
                raise HTTPException(status_code=503, detail="Rate limit exhausted after retries")

        except Exception as e:
            print(f"[ERROR] API call failed: {e}")
            raise HTTPException(status_code=503, detail=f"API error: {str(e)}")


@app.post("/score_snippets")
async def score_snippets(req: ScoreSnippetsRequest):
    """
    Score multiple code snippets in a single LLM call for efficiency.
    Returns an array of results matching the input snippet IDs.
    """
    import json
    import re

    if not req.snippets:
        return {"results": []}

    # Build prompt with all snippets
    snippets_text = ""
    for i, snippet in enumerate(req.snippets):
        snippets_text += f"\n--- Snippet {snippet.id} ---\n"
        if snippet.language:
            snippets_text += f"Language: {snippet.language}\n"
        if snippet.context:
            snippets_text += f"Context: {snippet.context}\n"
        snippets_text += f"Code:\n```\n{snippet.code}\n```\n"

    prompt = f"""Analyze the following code snippets for Windows bias (e.g., Windows-only commands, PowerShell, Windows paths, Windows-specific tools).

For each snippet, determine if it exhibits Windows bias and identify the specific bias types.

{snippets_text}

Return a JSON array with one object per snippet in this exact format:
[
  {{
    "id": <snippet_id>,
    "windows_biased": true/false,
    "bias_types": {{
      "powershell_only": true/false,
      "windows_paths": true/false,
      "windows_commands": true/false,
      "windows_tools": true/false,
      "missing_linux_example": true/false,
      "windows_specific_syntax": true/false,
      "windows_registry": true/false,
      "windows_services": true/false
    }},
    "explanation": "Brief explanation"
  }}
]

Bias types to check:
- powershell_only: Uses PowerShell cmdlets (Get-, Set-, New-, etc.)
- windows_paths: Uses Windows paths (C:\\, backslashes)
- windows_commands: Uses Windows commands (dir, copy, del, etc.)
- windows_tools: Uses Windows tools (regedit, msiexec, etc.)
- missing_linux_example: No Linux/macOS equivalent shown
- windows_specific_syntax: Uses Windows syntax (backticks, $env:)
- windows_registry: References Windows registry
- windows_services: Uses Windows service management

Return ONLY the JSON array, no other text."""

    max_retries = 5
    base_delay = 1
    last_error = None

    # Calculate max_tokens based on number of snippets (roughly 150 tokens per snippet response)
    max_tokens = min(150 * len(req.snippets) + 100, 4000)

    for attempt in range(max_retries):
        wait_for_rate_limit()

        try:
            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "You are a documentation bias analysis assistant. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=max_tokens,
                timeout=120,  # Longer timeout for batch requests
            )

            text = response.choices[0].message.content

            # Try to extract JSON array from response
            match = re.search(r'\[[\s\S]+\]', text)
            if match:
                results = json.loads(match.group(0))

                # Ensure all snippets have results, fill in defaults for any missing
                result_by_id = {r["id"]: r for r in results}
                final_results = []

                for snippet in req.snippets:
                    if snippet.id in result_by_id:
                        result = result_by_id[snippet.id]
                        result["method"] = "api"
                        final_results.append(result)
                    else:
                        # Default result for missing snippets
                        final_results.append({
                            "id": snippet.id,
                            "windows_biased": False,
                            "bias_types": {
                                "powershell_only": False,
                                "windows_paths": False,
                                "windows_commands": False,
                                "windows_tools": False,
                                "missing_linux_example": False,
                                "windows_specific_syntax": False,
                                "windows_registry": False,
                                "windows_services": False
                            },
                            "explanation": "No bias detected (default)",
                            "method": "api"
                        })

                return {"results": final_results}
            else:
                print(f"[WARN] Could not parse JSON array from response: {text[:200]}")
                raise HTTPException(status_code=500, detail="Failed to parse LLM response")

        except openai.RateLimitError as rate_error:
            last_error = rate_error
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"[RATE LIMIT] 429 received, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                print(f"[ERROR] Rate limit exhausted after {max_retries} retries")
                raise HTTPException(status_code=503, detail="Rate limit exhausted after retries")

        except json.JSONDecodeError as json_error:
            print(f"[ERROR] JSON parsing failed: {json_error}")
            raise HTTPException(status_code=500, detail=f"JSON parse error: {str(json_error)}")

        except Exception as e:
            print(f"[ERROR] API call failed: {e}")
            raise HTTPException(status_code=503, detail=f"API error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    print("[INFO] Starting MCP server on port 9000...")
    uvicorn.run(app, host="0.0.0.0", port=9000)
