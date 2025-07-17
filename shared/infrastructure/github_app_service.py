"""
GitHub App Authentication Service - Handles JWT token generation and installation tokens
"""
import jwt
import time
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from github import Github

from shared.config import config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class GitHubAppService:
    """Service for GitHub App authentication and token management"""
    
    def __init__(self):
        """Initialize GitHub App service with configuration"""
        self.app_id = config.github_app.app_id
        self.private_key = config.github_app.private_key
        self.installation_url = config.github_app.installation_url
        
        if not self.app_id or not self.private_key:
            logger.warning("GitHub App not configured - app_id or private_key missing")
            logger.warning(f"App ID: {bool(self.app_id)}, Private Key: {bool(self.private_key)}")
            self.configured = False
        else:
            logger.info(f"GitHub App configured - App ID: {self.app_id}")
            self.configured = True
    
    def generate_jwt_token(self) -> str:
        """Generate JWT token for GitHub App authentication"""
        if not self.configured:
            raise ValueError("GitHub App not configured")
        
        # JWT payload
        now = int(time.time())
        payload = {
            'iat': now,  # Issued at time
            'exp': now + (10 * 60),  # Expires in 10 minutes
            'iss': self.app_id  # Issuer (App ID)
        }
        
        # Generate JWT token
        token = jwt.encode(payload, self.private_key, algorithm='RS256')
        logger.info(f"Generated JWT token for app {self.app_id}")
        return token
    
    def get_installation_for_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get installation information for a specific user"""
        if not self.configured:
            logger.warning(f"GitHub App not configured, cannot get installation for {username}")
            return None
        
        try:
            logger.info(f"Getting installation for user: {username}")
            jwt_token = self.generate_jwt_token()
            
            # Get all installations for this app
            headers = {
                'Authorization': f'Bearer {jwt_token}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            response = requests.get(
                'https://api.github.com/app/installations',
                headers=headers
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get installations: {response.status_code} {response.text}")
                return None
            
            installations = response.json()
            logger.info(f"Found {len(installations)} total installations")
            
            # Log all installations for debugging
            for installation in installations:
                logger.info(f"Installation {installation['id']} for account: {installation['account']['login']}")
            
            # Find installation for the specific user
            for installation in installations:
                if installation['account']['login'].lower() == username.lower():
                    logger.info(f"Found installation {installation['id']} for user {username}")
                    return installation
            
            logger.warning(f"No installation found for user {username}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting installation for user {username}: {e}")
            return None
    
    def generate_installation_token(self, username: str) -> Optional[str]:
        """Generate installation access token for a specific user"""
        if not self.configured:
            return None
        
        try:
            # Get installation for user
            installation = self.get_installation_for_user(username)
            if not installation:
                logger.warning(f"Cannot generate installation token - no installation found for {username}")
                return None
            
            installation_id = installation['id']
            jwt_token = self.generate_jwt_token()
            
            # Generate installation access token
            headers = {
                'Authorization': f'Bearer {jwt_token}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            response = requests.post(
                f'https://api.github.com/app/installations/{installation_id}/access_tokens',
                headers=headers
            )
            
            if response.status_code != 201:
                logger.error(f"Failed to generate installation token: {response.status_code} {response.text}")
                return None
            
            token_data = response.json()
            access_token = token_data['token']
            
            logger.info(f"Generated installation token for user {username}")
            return access_token
            
        except Exception as e:
            logger.error(f"Error generating installation token for {username}: {e}")
            return None
    
    def create_github_client(self, username: str) -> Optional[Github]:
        """Create authenticated GitHub client using installation token"""
        if not self.configured:
            return None
        
        try:
            installation_token = self.generate_installation_token(username)
            if not installation_token:
                return None
            
            # Create GitHub client with installation token
            client = Github(installation_token)
            
            # Test the client and check permissions
            try:
                # Get installation details to see what repositories we can access
                installation = self.get_installation_for_user(username)
                if installation:
                    logger.info(f"App has access to {installation.get('repository_selection', 'unknown')} repositories")
                    
                # Try to access the user's repositories
                try:
                    user_repos = list(client.get_user(username).get_repos())[:5]  # Get first 5 repos
                    logger.info(f"Can access {len(user_repos)} repositories for {username}")
                    for repo in user_repos:
                        logger.info(f"  - {repo.full_name}")
                except Exception as repo_error:
                    logger.warning(f"Cannot access repositories for {username}: {repo_error}")
                    
            except Exception as test_error:
                logger.warning(f"Error testing GitHub App client: {test_error}")
            
            logger.info(f"Created GitHub App client for {username}")
            return client
            
        except Exception as e:
            logger.error(f"Error creating GitHub App client for {username}: {e}")
            return None
    
    def is_user_installation_available(self, username: str) -> bool:
        """Check if user has the GitHub App installed"""
        if not self.configured:
            return False
        
        installation = self.get_installation_for_user(username)
        return installation is not None
    
    def get_installation_url(self) -> str:
        """Get the URL for users to install the GitHub App"""
        return self.installation_url or f"https://github.com/apps/{self.app_id}/installations/new"


# Global service instance
github_app_service = GitHubAppService()