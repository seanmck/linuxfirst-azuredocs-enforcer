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

@app.post("/score_page")
async def score_page(req: ScorePageRequest):
    import json
    import re

    prompt = f"""
You are an expert in cross-platform documentation analysis.
Analyze the following documentation page for evidence of Windows bias, such as only Windows/Powershell examples being given, Windows tools/patterns being mentioned exclusively or at least before their Linux equivalents. Return a JSON summary with:
- bias_types: list of bias types found (e.g., 'powershell_heavy', 'windows_first', 'missing_linux_example', 'windows_tools')
- summary: a short summary of the bias
- recommendations: suggestions to improve Linux parity

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

if __name__ == "__main__":
    import uvicorn
    print("[INFO] Starting MCP server on port 9000...")
    uvicorn.run(app, host="0.0.0.0", port=9000)
