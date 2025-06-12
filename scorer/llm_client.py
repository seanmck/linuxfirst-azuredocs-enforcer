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
        openai.azure_endpoint = self.api_base
        openai.api_key = self.api_key
        openai.api_version = "2023-05-15"  # Update if your Azure deployment uses a different version

    def build_prompt(self, snippet, context):
        return f"""
You are an expert in cross-platform documentation. Review the following code snippet and its context. Does it exhibit a Windows bias (e.g., Windows-only commands, PowerShell, or Windows-centric tools), even if the documentation is not explicitly OS-specific? Reply 'Yes' or 'No' and briefly explain why.

Context: {context}
Code:
{snippet}
"""

    def score_snippet(self, snippet_dict):
        prompt = (
            "You are an expert in technical documentation. "
            "Given the following code snippet and its context, "
            "determine if it is Windows-specific and whether the documentation "
            "fails to provide Linux/macOS equivalents. "
            "Reply with a JSON object: "
            '{"windows_biased": true/false, "missing_linux_example": true/false, "explanation": "..."}'
            "\n\nContext:\n" + snippet_dict.get('context', '') + "\n\nCode:\n" + snippet_dict.get('code', '') + "\n"
        )
        response = openai.chat.completions.create(
            model=self.deployment,  # Azure uses 'model' for deployment name in openai>=1.0.0
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        content = response.choices[0].message.content
        try:
            json_str = re.search(r'\{.*\}', content, re.DOTALL).group(0)
            return json.loads(json_str)
        except Exception:
            return {"windows_biased": None, "missing_linux_example": None, "explanation": content}

# Example usage:
# client = LLMClient()
# result = client.score_snippet({'code': 'dir', 'context': 'Example'})
# print(result)
