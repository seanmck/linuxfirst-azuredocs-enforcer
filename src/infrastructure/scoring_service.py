"""
ScoringService - Handles bias detection and scoring functionality
Extracted from the monolithic queue_worker.py
"""
import os
from typing import Dict, List, Optional, Any
from scorer.heuristics import is_windows_biased
from scorer.llm_client import LLMClient
from src.shared.config import config
from src.shared.utils.http_client import post_json
from src.shared.utils.metrics import get_metrics


class ScoringService:
    """Service responsible for bias detection and scoring operations"""
    
    def __init__(self, mcp_server_url: Optional[str] = None):
        self.llm_client = LLMClient()
        self.mcp_server_url = mcp_server_url or os.getenv("MCP_SERVER_URL", "http://localhost:8001/score_page")
        self.metrics = get_metrics()

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

    def apply_llm_scoring(self, snippets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply LLM-based scoring to snippets
        
        Args:
            snippets: List of snippet dictionaries
            
        Returns:
            List of snippets with LLM scores added
        """
        print(f"[INFO] Scoring {len(snippets)} snippets with LLM...")
        
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