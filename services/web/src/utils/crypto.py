"""
Simple encryption utilities for storing sensitive data
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

logger = logging.getLogger(__name__)

# Get or generate encryption key
_ENCRYPTION_KEY = None


def get_encryption_key() -> bytes:
    """Get or generate the encryption key"""
    global _ENCRYPTION_KEY
    
    if _ENCRYPTION_KEY:
        return _ENCRYPTION_KEY
    
    # Try to get from environment
    key_str = os.environ.get("ENCRYPTION_KEY")
    if key_str:
        _ENCRYPTION_KEY = base64.urlsafe_b64decode(key_str.encode())
        return _ENCRYPTION_KEY
    
    # Generate from a secret and salt
    secret = os.environ.get("ENCRYPTION_SECRET", "default-secret-change-me")
    salt = os.environ.get("ENCRYPTION_SALT", "default-salt-change-me").encode()
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    _ENCRYPTION_KEY = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    
    if secret == "default-secret-change-me":
        logger.warning("Using default encryption secret. Set ENCRYPTION_SECRET in production!")
    
    return _ENCRYPTION_KEY


def encrypt_token(token: str) -> str:
    """Encrypt a token for storage"""
    if not token:
        return ""
    
    try:
        f = Fernet(get_encryption_key())
        encrypted = f.encrypt(token.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    except Exception as e:
        logger.error(f"Failed to encrypt token: {e}")
        # In development, return plain token with warning
        if os.environ.get("ENVIRONMENT") == "development":
            logger.warning("Returning unencrypted token in development mode")
            return token
        raise


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a stored token"""
    if not encrypted_token:
        return ""
    
    try:
        f = Fernet(get_encryption_key())
        decoded = base64.urlsafe_b64decode(encrypted_token.encode())
        decrypted = f.decrypt(decoded)
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Failed to decrypt token: {e}")
        # In development, assume it might be unencrypted
        if os.environ.get("ENVIRONMENT") == "development":
            logger.warning("Assuming token is unencrypted in development mode")
            return encrypted_token
        raise