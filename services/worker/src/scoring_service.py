"""
ScoringService - Handles bias detection and scoring functionality
Extracted from the monolithic queue_worker.py
"""
import os
from typing import Dict, List, Optional, Any, Iterator
from packages.scorer.heuristics import is_windows_biased
from packages.scorer.llm_client import LLMClient
from shared.config import config
from shared.utils.http_client import post_json
from shared.utils.metrics import get_metrics


def chunk_list(items: List[Any], size: int) -> Iterator[List[Any]]:
    """Split a list into chunks of specified size."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


class ScoringService:
    """Service responsible for bias detection and scoring operations"""
    
    def __init__(self, mcp_server_url: Optional[str] = None):
        self.llm_client = LLMClient()
        base_url = mcp_server_url or os.getenv("MCP_SERVER_URL", "http://localhost:9000/score_page")
        # Extract base URL without endpoint path
        if base_url.endswith("/score_page"):
            self.mcp_base_url = base_url[:-len("/score_page")]
        else:
            self.mcp_base_url = base_url.rstrip("/")
        self.mcp_server_url = f"{self.mcp_base_url}/score_page"
        self.mcp_snippets_url = f"{self.mcp_base_url}/score_snippets"
        self.metrics = get_metrics()
        # Use centralized config for batch size
        self.batch_size = config.azure_openai.llm_batch_size

    def apply_heuristic_scoring(self, snippets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply heuristic-based Windows bias detection to snippets

        Args:
            snippets: List of snippet dictionaries with 'code' and 'context'

        Returns:
            List of snippets that were flagged by heuristics
        """
        flagged = []

        for snippet in snippets:
            if is_windows_biased(snippet):
                flagged.append(snippet)
                # Record heuristic bias detection
                self.metrics.record_bias_detected('heuristic', 'windows')

        print(f"[INFO] {len(flagged)} snippets flagged by heuristics.")
        return flagged

    def _create_heuristic_score(self, snippet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create an LLM-score-compatible dict using heuristic detection.
        Used as fallback when batch LLM scoring fails.
        """
        biased = is_windows_biased(snippet)
        code = snippet.get('code', '').lower()

        return {
            "windows_biased": biased,
            "bias_types": {
                "powershell_only": 'powershell' in code or bool(any(
                    cmd in code for cmd in ['get-', 'set-', 'new-', 'remove-']
                )),
                "windows_paths": bool('c:\\' in code or '\\users\\' in code),
                "windows_commands": bool(any(
                    cmd in code for cmd in ['dir', 'copy', 'del', 'cls', 'type']
                )),
                "windows_tools": bool(any(
                    tool in code for tool in ['regedit', 'msiexec', 'choco', 'winget']
                )),
                "missing_linux_example": biased,
                "windows_specific_syntax": bool('$env:' in code),
                "windows_registry": 'registry' in code or 'regedit' in code,
                "windows_services": bool(any(
                    svc in code for svc in ['net start', 'net stop', 'sc ']
                ))
            },
            "explanation": "Heuristic fallback (batch scoring timed out)" if biased else "No bias detected (heuristic fallback)",
            "method": "heuristic_fallback"
        }

    def apply_llm_scoring(self, snippets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply LLM-based scoring to snippets using batch requests for efficiency.

        Args:
            snippets: List of snippet dictionaries

        Returns:
            List of snippets with LLM scores added
        """
        if not snippets:
            return snippets

        print(f"[INFO] Scoring {len(snippets)} snippets with LLM (batch size: {self.batch_size})...")

        # Use batch scoring if batch_size > 1 and we have the MCP server URL
        if self.batch_size > 1:
            return self._apply_batch_scoring(snippets)
        else:
            # Fallback to individual scoring
            return self._apply_individual_scoring(snippets)

    def _apply_batch_scoring(self, snippets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Score snippets in batches using the /score_snippets endpoint.
        """
        total_batches = (len(snippets) + self.batch_size - 1) // self.batch_size
        batch_num = 0

        for batch in chunk_list(snippets, self.batch_size):
            batch_num += 1
            print(f"[LLM] Scoring batch {batch_num}/{total_batches} ({len(batch)} snippets)")

            # Prepare batch payload with snippet IDs
            batch_payload = []
            snippet_id_map = {}

            for idx, snippet in enumerate(batch):
                # Use index as ID if snippet doesn't have one
                snippet_id = snippet.get('id', idx)
                snippet_id_map[snippet_id] = snippet

                batch_payload.append({
                    "id": snippet_id,
                    "code": snippet.get('code', ''),
                    "language": snippet.get('language', ''),
                    "context": snippet.get('context', '')
                })

            try:
                # Use metrics context manager to track API call
                with self.metrics.time_api_request('mcp_server_batch', 'POST'):
                    response = post_json(
                        self.mcp_snippets_url,
                        {"snippets": batch_payload},
                        timeout=120  # Longer timeout for batch requests
                    )

                if response.status_code == 200:
                    results = response.json().get("results", [])

                    # Map results back to snippets
                    for result in results:
                        snippet_id = result.get("id")
                        if snippet_id in snippet_id_map:
                            snippet_id_map[snippet_id]['llm_score'] = result
                else:
                    print(f"[WARN] Batch scoring failed with status {response.status_code}, falling back to heuristic scoring")
                    for snippet in batch:
                        snippet['llm_score'] = self._create_heuristic_score(snippet)

            except Exception as e:
                print(f"[WARN] Batch scoring error: {e}, falling back to heuristic scoring")
                for snippet in batch:
                    snippet['llm_score'] = self._create_heuristic_score(snippet)

        return snippets

    def _apply_individual_scoring(self, snippets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Score snippets individually using the LLM client (fallback method).
        """
        for i, snippet in enumerate(snippets):
            print(f"[LLM] Scoring snippet {i+1}/{len(snippets)} from {snippet.get('url', 'unknown')}")
            snippet['llm_score'] = self.llm_client.score_snippet(snippet)

        return snippets

    def apply_mcp_holistic_scoring(self, page_content: str, page_url: str) -> Optional[Dict[str, Any]]:
        """
        Apply MCP holistic scoring to a page
        
        Args:
            page_content: Full page content (HTML or markdown)
            page_url: URL of the page
            
        Returns:
            MCP scoring result or None if error
        """
        try:
            print(f"[MCP] Sending page to MCP server: {page_url}")
            
            # Use metrics context manager to track API call
            with self.metrics.time_api_request('mcp_server', 'POST'):
                response = post_json(
                    self.mcp_server_url,
                    {
                        "page_content": page_content,
                        "metadata": {"url": page_url}
                    },
                    timeout=60
                )
            
            print(f"[MCP] MCP server response status: {response.status_code}")
            
            if response.status_code == 200:
                mcp_result = response.json()
                print(f"[MCP] Holistic score for {page_url}: {mcp_result}")
                return mcp_result
            else:
                print(f"[MCP] Error from MCP server for {page_url}: {response.status_code} {response.text}")
                return None
                
        except Exception as e:
            print(f"[MCP] Exception contacting MCP server for {page_url}: {e}")
            return None

    def get_bias_metrics(self, snippets: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Calculate bias metrics from scored snippets
        
        Args:
            snippets: List of snippets with LLM scores
            
        Returns:
            Dictionary with bias metrics
        """
        biased_snippets = [
            s for s in snippets 
            if s.get('llm_score', {}).get('windows_biased')
        ]
        
        # Get unique URLs that contain biased snippets
        biased_urls = set(s.get('url') for s in biased_snippets if s.get('url'))
        
        return {
            'biased_pages_count': len(biased_urls),
            'flagged_snippets_count': len(biased_snippets)
        }

    def score_snippet_batch(
        self, 
        snippets: List[Dict[str, Any]], 
        use_heuristics: bool = True,
        use_llm: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Apply complete scoring pipeline to a batch of snippets
        
        Args:
            snippets: List of snippet dictionaries
            use_heuristics: Whether to apply heuristic filtering first
            use_llm: Whether to apply LLM scoring
            
        Returns:
            List of scored snippets
        """
        # Start with all snippets or heuristic-filtered ones
        if use_heuristics:
            flagged_snippets = self.apply_heuristic_scoring(snippets)
            # If no snippets flagged by heuristics, use all snippets
            if not flagged_snippets:
                flagged_snippets = snippets
        else:
            flagged_snippets = snippets
            
        # Apply LLM scoring if requested
        if use_llm:
            flagged_snippets = self.apply_llm_scoring(flagged_snippets)
            
        return flagged_snippets