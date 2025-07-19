"""
Simple in-memory cache for docset statistics with TTL support.
Provides significant performance improvements for frequently accessed docsets.
"""

import time
from typing import Dict, Any, Optional
from threading import Lock
import json


class DocsetCache:
    """Thread-safe in-memory cache for docset statistics."""
    
    def __init__(self, default_ttl: int = 300):  # 5 minutes default TTL
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.lock = Lock()
        self.default_ttl = default_ttl
    
    def get(self, doc_set: str) -> Optional[Dict[str, Any]]:
        """Get cached docset data if not expired."""
        with self.lock:
            if doc_set not in self.cache:
                return None
            
            entry = self.cache[doc_set]
            if time.time() > entry['expires_at']:
                # Entry expired, remove it
                del self.cache[doc_set]
                return None
            
            return entry['data']
    
    def set(self, doc_set: str, data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Store docset data in cache with TTL."""
        if ttl is None:
            ttl = self.default_ttl
        
        with self.lock:
            self.cache[doc_set] = {
                'data': data,
                'expires_at': time.time() + ttl,
                'created_at': time.time()
            }
    
    def invalidate(self, doc_set: str) -> None:
        """Remove specific docset from cache."""
        with self.lock:
            if doc_set in self.cache:
                del self.cache[doc_set]
    
    def invalidate_all(self) -> None:
        """Clear all cached data."""
        with self.lock:
            self.cache.clear()
    
    def cleanup_expired(self) -> int:
        """Remove expired entries from cache. Returns count of removed entries."""
        current_time = time.time()
        expired_keys = []
        
        with self.lock:
            for key, entry in self.cache.items():
                if current_time > entry['expires_at']:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.cache[key]
        
        return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.lock:
            active_entries = 0
            expired_entries = 0
            current_time = time.time()
            
            for entry in self.cache.values():
                if current_time > entry['expires_at']:
                    expired_entries += 1
                else:
                    active_entries += 1
            
            return {
                'total_entries': len(self.cache),
                'active_entries': active_entries,
                'expired_entries': expired_entries,
                'cache_size_bytes': len(json.dumps(self.cache, default=str))
            }


# Global cache instance
_docset_cache = DocsetCache(default_ttl=300)  # 5 minutes


def get_cache() -> DocsetCache:
    """Get the global docset cache instance."""
    return _docset_cache


def get_cached_docset_data(doc_set: str) -> Optional[Dict[str, Any]]:
    """Get cached docset data."""
    return _docset_cache.get(doc_set)


def cache_docset_data(doc_set: str, data: Dict[str, Any], ttl: Optional[int] = None) -> None:
    """Cache docset data."""
    _docset_cache.set(doc_set, data, ttl)


def invalidate_docset_cache(doc_set: str) -> None:
    """Invalidate cached data for a specific docset."""
    _docset_cache.invalidate(doc_set)


def invalidate_all_docset_cache() -> None:
    """Invalidate all cached docset data."""
    _docset_cache.invalidate_all()