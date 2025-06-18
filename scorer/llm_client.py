# llm_client.py
# Wraps OpenAI API and prompt logic for snippet scoring.

import os
import openai
import re
import json

class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("AZURE_OPENAI_KEY")
        self.api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        
        # Check if we have the required credentials
        self.api_available = all([self.api_key, self.api_base, self.deployment])
        
        if self.api_available:
            try:
                # Initialize the client with Azure OpenAI configuration
                self.client = openai.AzureOpenAI(
                    api_key=self.api_key,
                    api_version="2023-05-15",  # Update if your Azure deployment uses a different version
                    azure_endpoint=self.api_base
                )
            except Exception as e:
                print(f"[WARNING] Failed to initialize Azure OpenAI client: {e}")
                self.api_available = False
        else:
            print("[WARNING] Azure OpenAI credentials not found. Using heuristic fallback for bias detection.")
            self.client = None

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
        
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,  # Azure OpenAI: use deployment name as model
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
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
        except Exception as e:
            print(f"[WARNING] API call failed, falling back to heuristics: {e}")
            return self._heuristic_score(snippet_dict)

# Example usage:
# client = LLMClient()
# result = client.score_snippet({'code': 'dir', 'context': 'Example'})
# print(result)
