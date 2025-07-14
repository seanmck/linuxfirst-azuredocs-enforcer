# llm_client.py
# Wraps OpenAI API and prompt logic for snippet scoring.

import os
import openai
import re
import json
import time
import random
import threading
from collections import deque
from shared.utils.metrics import get_metrics
from shared.utils.logging import get_logger

class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("AZURE_OPENAI_KEY")
        self.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        self.client_id = os.getenv("AZURE_OPENAI_CLIENTID")
        
        # Initialize logger
        self.logger = get_logger(__name__)
        
        # Rate limiting: Azure OpenAI typical limits
        # Adjust these based on your actual limits
        self.requests_per_minute = int(os.getenv("AZURE_OPENAI_RPM", "60"))  # Default 60 RPM
        self.min_request_interval = 60.0 / self.requests_per_minute
        self.request_times = deque(maxlen=self.requests_per_minute)
        self.rate_limit_lock = threading.Lock()
        
        # Check if we have the required credentials (either API key or managed identity)
        self.api_available = self.api_base and (self.api_key or self.client_id)
        
        if self.api_available:
            try:
                if self.client_id and not self.api_key:
                    # Use managed identity authentication (for cloud deployment)
                    from azure.identity import ManagedIdentityCredential
                    credential = ManagedIdentityCredential(client_id=self.client_id)
                    
                    def get_bearer_token_provider():
                        return credential.get_token("https://cognitiveservices.azure.com/.default").token
                    
                    self.client = openai.AzureOpenAI(
                        azure_ad_token_provider=get_bearer_token_provider,
                        api_version="2023-05-15",
                        azure_endpoint=self.api_base
                    )
                    self.auth_method = "managed_identity"
                else:
                    # Use API key authentication (for local development)
                    self.client = openai.AzureOpenAI(
                        api_key=self.api_key,
                        api_version="2023-05-15",
                        azure_endpoint=self.api_base
                    )
                    self.auth_method = "api_key"
            except Exception as e:
                self.logger.warning(f"Failed to initialize Azure OpenAI client: {e}")
                self.api_available = False
        else:
            self.logger.warning("Azure OpenAI credentials not found. Using heuristic fallback for bias detection.")
            self.client = None
        
        # Initialize metrics
        self.metrics = get_metrics()

    def build_prompt(self, snippet, context):
        return f"""
You are an expert in cross-platform documentation. Review the following code snippet and its context. Does it exhibit a Windows bias (e.g., Windows-only commands, PowerShell, or Windows-centric tools), even if the documentation is not explicitly OS-specific? Reply 'Yes' or 'No' and briefly explain why.

Context: {context}
Code:
{snippet}
"""

    def _heuristic_score(self, snippet_dict):
        """Fallback scoring using simple heuristics when API is not available."""
        code = snippet_dict.get('code', '').lower()
        context = snippet_dict.get('context', '').lower()
        
        # Simple heuristics for Windows bias detection
        windows_indicators = [
            'powershell', 'ps1', 'get-', 'set-', 'new-', 'remove-', 'start-', 'stop-',
            'dir ', 'copy ', 'del ', 'move ', 'ren ', 'md ', 'rd ',
            'c:\\', 'd:\\', 'e:\\', 'f:\\', 'g:\\', 'h:\\',
            'regedit', 'msiexec', 'wmic', 'netsh',
            'windows service', 'windows registry', 'windows path',
            '.exe', '.msi', '.bat', '.cmd',
            'backtick', '`', '${env:', '$env:',
            'windows', 'win32', 'win64'
        ]
        
        bias_found = any(indicator in code or indicator in context for indicator in windows_indicators)
        
        return {
            "windows_biased": bias_found,
            "bias_types": {
                'powershell_only': 'powershell' in code or 'ps1' in code,
                'windows_paths': any(path in code for path in ['c:\\', 'd:\\', 'e:\\', 'f:\\', 'g:\\', 'h:\\']),
                'windows_commands': any(cmd in code for cmd in ['dir ', 'copy ', 'del ', 'move ', 'ren ', 'md ', 'rd ']),
                'windows_tools': any(tool in code for tool in ['regedit', 'msiexec', 'wmic', 'netsh']),
                'missing_linux_example': bias_found,  # If Windows bias found, likely missing Linux example
                'windows_specific_syntax': any(syntax in code for syntax in ['backtick', '`', '${env:', '$env:']),
                'windows_registry': 'registry' in code or 'regedit' in code,
                'windows_services': 'service' in code and ('windows' in code or 'start' in code or 'stop' in code)
            },
            "explanation": f"Heuristic detection: {'Windows bias detected' if bias_found else 'No obvious Windows bias'}",
            "suggested_linux_alternative": "Consider providing equivalent Linux/macOS commands or cross-platform alternatives.",
            "method": "heuristic"
        }

    def _wait_for_rate_limit(self):
        """Ensure we don't exceed rate limits by waiting if necessary"""
        with self.rate_limit_lock:
            now = time.time()
            
            # Clean up old request times
            while self.request_times and self.request_times[0] < now - 60:
                self.request_times.popleft()
            
            # If we're at the limit, wait
            if len(self.request_times) >= self.requests_per_minute:
                oldest_request = self.request_times[0]
                wait_time = 60 - (now - oldest_request) + 0.1  # Add small buffer
                if wait_time > 0:
                    self.logger.info(f"Rate limit reached, waiting {wait_time:.1f} seconds")
                    time.sleep(wait_time)
                    now = time.time()
            
            # Also ensure minimum interval between requests
            if self.request_times:
                last_request = self.request_times[-1]
                time_since_last = now - last_request
                if time_since_last < self.min_request_interval:
                    wait_time = self.min_request_interval - time_since_last
                    time.sleep(wait_time)
                    now = time.time()
            
            # Record this request
            self.request_times.append(now)

    def score_snippet(self, snippet_dict):
        # If API is not available, use heuristic fallback
        if not self.api_available:
            return self._heuristic_score(snippet_dict)
        
        prompt = (
            "You are an expert in cross-platform technical documentation. "
            "Given the following code snippet and its context, analyze it for Windows bias. "
            "Reply with a JSON object containing the following fields:\n"
            '{\n'
            '  "windows_biased": true/false,\n'
            '  "bias_types": {\n'
            '    "powershell_only": true/false,\n'
            '    "windows_paths": true/false,\n'
            '    "windows_commands": true/false,\n'
            '    "windows_tools": true/false,\n'
            '    "missing_linux_example": true/false,\n'
            '    "windows_specific_syntax": true/false,\n'
            '    "windows_registry": true/false,\n'
            '    "windows_services": true/false\n'
            '  },\n'
            '  "explanation": "Detailed explanation of the bias found",\n'
            '  "suggested_linux_alternative": "How to achieve the same on Linux/macOS"\n'
            '}\n\n'
            "Bias types to check for:\n"
            "- powershell_only: Uses PowerShell cmdlets or syntax\n"
            "- windows_paths: Uses Windows-style paths (C:\\, backslashes)\n"
            "- windows_commands: Uses Windows-specific commands (dir, copy, del, etc.)\n"
            "- windows_tools: Uses Windows-only tools (regedit, msiexec, etc.)\n"
            "- missing_linux_example: No equivalent Linux/macOS example provided\n"
            "- windows_specific_syntax: Uses Windows-specific syntax (backticks, etc.)\n"
            "- windows_registry: References Windows registry\n"
            "- windows_services: Uses Windows service management\n\n"
            "Context:\n" + snippet_dict.get('context', '') + "\n\nCode:\n" + snippet_dict.get('code', '') + "\n"
        )
        
        # Implement retry logic with exponential backoff for rate limiting
        max_retries = 5
        base_delay = 1
        response = None
        
        for attempt in range(max_retries):
            try:
                # Apply rate limiting before making request
                self._wait_for_rate_limit()
                
                # Record API request metrics
                start_time = time.time()
                try:
                    response = self.client.chat.completions.create(
                        model=self.deployment,  # Azure OpenAI: use deployment name as model
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0
                    )
                    # Record successful API call
                    self.metrics.record_api_request('azure_openai', 'POST', 200, time.time() - start_time)
                    break  # Success, exit retry loop
                except Exception as api_error:
                    # Record failed API call
                    status_code = getattr(api_error, 'status_code', 500)
                    self.metrics.record_api_request('azure_openai', 'POST', status_code, time.time() - start_time)
                    
                    # Check if it's a rate limit error
                    if status_code == 429:
                        if attempt < max_retries - 1:
                            # Extract retry-after from error message if available
                            retry_after = base_delay
                            error_msg = str(api_error)
                            if 'Try again in' in error_msg:
                                try:
                                    # Extract seconds from error message
                                    import re
                                    match = re.search(r'Try again in (\d+) seconds', error_msg)
                                    if match:
                                        retry_after = int(match.group(1))
                                except:
                                    pass
                            
                            # Add jitter to prevent thundering herd
                            delay = retry_after + random.uniform(0, 1)
                            self.logger.warning(f"Rate limited. Retrying in {delay:.1f} seconds (attempt {attempt + 1}/{max_retries})")
                            time.sleep(delay)
                            
                            # Exponential backoff for subsequent retries
                            base_delay = min(base_delay * 2, 60)
                            continue
                    raise
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.warning(f"API call failed after {max_retries} attempts, falling back to heuristics: {e}")
                    return self._heuristic_score(snippet_dict)
        
        # Process the response if we got one
        if response:
            content = response.choices[0].message.content
            try:
                json_str = re.search(r'\{.*\}', content, re.DOTALL).group(0)
                result = json.loads(json_str)
                # Ensure backward compatibility with existing data
                if 'bias_types' not in result:
                    result['bias_types'] = {
                        'powershell_only': False,
                        'windows_paths': False,
                        'windows_commands': False,
                        'windows_tools': False,
                        'missing_linux_example': result.get('missing_linux_example', False),
                        'windows_specific_syntax': False,
                        'windows_registry': False,
                        'windows_services': False
                    }
                if 'suggested_linux_alternative' not in result:
                    result['suggested_linux_alternative'] = ""
                result['method'] = 'api'
                return result
            except Exception as e:
                return {
                    "windows_biased": None, 
                    "bias_types": {
                        'powershell_only': False,
                        'windows_paths': False,
                        'windows_commands': False,
                        'windows_tools': False,
                        'missing_linux_example': False,
                        'windows_specific_syntax': False,
                        'windows_registry': False,
                        'windows_services': False
                    },
                    "explanation": content,
                    "suggested_linux_alternative": "",
                    "parse_error": str(e),
                    "method": "api"
                }
        else:
            # Should not reach here, but just in case
            return self._heuristic_score(snippet_dict)

# Example usage:
# client = LLMClient()
# result = client.score_snippet({'code': 'dir', 'context': 'Example'})
# print(result)
