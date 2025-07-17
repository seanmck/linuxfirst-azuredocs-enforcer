"""
Session storage utilities with Redis and in-memory fallback
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import redis

logger = logging.getLogger(__name__)

# Try to create Redis client
redis_client = None
try:
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
    REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
    
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD if REDIS_PASSWORD else None,
        decode_responses=True
    )
    redis_client.ping()
    logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    logger.warning(f"Failed to connect to Redis: {e}. Using in-memory session storage.")
    redis_client = None


class SessionStorage:
    """Session storage with Redis and in-memory fallback"""
    
    def __init__(self, prefix: str = "session"):
        self.prefix = prefix
        self.memory_storage: Dict[str, Dict[str, Any]] = {}
    
    def set(self, key: str, value: Dict[str, Any], ttl: int = 86400):
        """Set a session value with TTL in seconds"""
        full_key = f"{self.prefix}:{key}"
        
        if redis_client:
            try:
                redis_client.setex(
                    full_key,
                    ttl,
                    json.dumps(value, default=str)
                )
                return
            except Exception as e:
                logger.error(f"Failed to store in Redis: {e}")
        
        # Fallback to memory
        self.memory_storage[full_key] = {
            "value": value,
            "expires_at": datetime.utcnow() + timedelta(seconds=ttl)
        }
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a session value"""
        full_key = f"{self.prefix}:{key}"
        
        if redis_client:
            try:
                result = redis_client.get(full_key)
                if result:
                    return json.loads(result)
                return None
            except Exception as e:
                logger.error(f"Failed to get from Redis: {e}")
        
        # Fallback to memory
        if full_key in self.memory_storage:
            data = self.memory_storage[full_key]
            if data["expires_at"] > datetime.utcnow():
                return data["value"]
            else:
                # Clean up expired session
                del self.memory_storage[full_key]
        
        return None
    
    def delete(self, key: str):
        """Delete a session value"""
        full_key = f"{self.prefix}:{key}"
        
        if redis_client:
            try:
                redis_client.delete(full_key)
                return
            except Exception as e:
                logger.error(f"Failed to delete from Redis: {e}")
        
        # Fallback to memory
        if full_key in self.memory_storage:
            del self.memory_storage[full_key]
    
    def cleanup_expired(self):
        """Clean up expired sessions (only needed for memory storage)"""
        if not redis_client:
            now = datetime.utcnow()
            expired_keys = [
                key for key, data in self.memory_storage.items()
                if data["expires_at"] <= now
            ]
            for key in expired_keys:
                del self.memory_storage[key]
            
            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired sessions")


# Global session storage instance
_session_storage = None


def get_session_storage(prefix: str = "session") -> SessionStorage:
    """Get or create the global session storage instance"""
    global _session_storage
    if _session_storage is None:
        _session_storage = SessionStorage(prefix)
    return _session_storage