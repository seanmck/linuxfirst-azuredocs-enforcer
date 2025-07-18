from fastapi import FastAPI, Request
from pydantic import BaseModel
import os
import openai
from azure.identity import ManagedIdentityCredential

app = FastAPI()

# AOAI config from environment
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-35-turbo")
AZURE_OPENAI_CLIENTID = os.getenv("AZURE_OPENAI_CLIENTID", "")

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
    prompt = f"""
You are an expert in cross-platform documentation analysis.
Analyze the following documentation page for evidence of Windows bias, such as only Windows/Powershell examples being given, Windows tools/patterns being mentioned exclusively or at least before their Linux equivalents. Return a JSON summary with:
- bias_types: list of bias types found (e.g., 'powershell_heavy', 'windows_first', 'missing_linux_example', 'windows_tools')
- summary: a short summary of the bias
- recommendations: suggestions to improve Linux parity

Page content:
{req.page_content}
"""
    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,  # Azure OpenAI: use deployment name as model
            messages=[{"role": "system", "content": "You are a documentation bias analysis assistant."},
                      {"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=512,
        )
        # Try to extract JSON from the response
        import json
        import re
        text = response.choices[0].message.content
        match = re.search(r'\{[\s\S]+\}', text)
        if match:
            result = json.loads(match.group(0))
        else:
            result = {"raw": text}
        return result
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    print("[INFO] Starting MCP server on port 8009...")
    uvicorn.run(app, host="0.0.0.0", port=8009)
