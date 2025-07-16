"""
GitHub Pull Request Service - Handles PR creation from user accounts
"""
import os
import re
import time
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
from github import Github, GithubException
from github.Repository import Repository
from github.Branch import Branch
from github.ContentFile import ContentFile
import logging

from shared.config import config
from shared.utils.logging import get_logger
from shared.infrastructure.github_app_service import github_app_service
import requests

logger = get_logger(__name__)


class GitHubPRService:
    """Service for creating GitHub pull requests from user accounts"""
    
    def __init__(self, access_token: str = None, username: str = None):
        """Initialize with user's GitHub access token or username for app auth"""
        self.logger = logger
        self.username = username
        
        # Try GitHub App first if username provided
        if username and github_app_service.configured:
            self.logger.info(f"Attempting GitHub App authentication for user: {username}")
            app_client = github_app_service.create_github_client(username)
            if app_client:
                self.github_client = app_client
                # For GitHub Apps, we don't get a specific user - we act as the app
                self.user = None  # Will be set differently for apps
                self.auth_method = "github_app"
                self.username = username
                self.logger.info(f"Successfully authenticated via GitHub App for {username}")
                return
            else:
                self.logger.warning(f"GitHub App authentication failed for {username}, falling back to OAuth")
        
        # Fallback to OAuth token
        if not access_token:
            raise ValueError("Either access_token or username must be provided")
        
        self.github_client = Github(access_token)
        self.user = self.github_client.get_user()
        self.auth_method = "oauth"
        
        # Log basic user info and token scopes for debugging
        try:
            self.logger.info(f"GitHub user: {self.user.login}")
            self.logger.info(f"User permissions: {self.user.permissions}")
            
            # Check token scopes
            headers = {"Authorization": f"token {access_token}"}
            response = requests.get("https://api.github.com/user", headers=headers)
            if response.status_code == 200:
                scopes = response.headers.get('X-OAuth-Scopes', '')
                self.logger.info(f"Token scopes: {scopes}")
            else:
                self.logger.warning(f"Failed to fetch user info for scope check: {response.status_code}")
        except Exception as e:
            self.logger.error(f"Error checking user permissions: {e}")
        
    async def check_user_fork(self, repo_full_name: str) -> Optional[Repository]:
        """Check if user has a fork of the repository"""
        try:
            # Get the original repository
            original_repo = self.github_client.get_repo(repo_full_name)
            
            # Check user's repositories for a fork
            for repo in self.user.get_repos():
                if repo.fork and repo.parent and repo.parent.full_name == repo_full_name:
                    self.logger.info(f"Found existing fork: {repo.full_name}")
                    return repo
            
            return None
        except GithubException as e:
            self.logger.error(f"Error checking for fork: {e}")
            raise
    
    async def create_fork(self, repo_full_name: str) -> Repository:
        """Create a fork of the repository"""
        try:
            original_repo = self.github_client.get_repo(repo_full_name)
            self.logger.info(f"Creating fork of {repo_full_name}")
            
            # Check if user has permission to fork
            try:
                can_fork = original_repo.permissions.admin or original_repo.permissions.push or original_repo.permissions.pull
                self.logger.info(f"User permissions on {repo_full_name}: admin={original_repo.permissions.admin}, push={original_repo.permissions.push}, pull={original_repo.permissions.pull}")
                
                if not can_fork:
                    self.logger.warning(f"User may not have permission to fork {repo_full_name}")
                    
            except Exception as perm_error:
                self.logger.warning(f"Could not check permissions on {repo_full_name}: {perm_error}")
            
            # Create the fork
            fork = self.user.create_fork(original_repo)
            
            # GitHub fork creation is async, wait for it to be ready
            await self.wait_for_fork_ready(fork.full_name)
            
            return fork
        except GithubException as e:
            self.logger.error(f"Error creating fork: {e}")
            self.logger.error(f"GitHub exception status: {e.status}")
            self.logger.error(f"GitHub exception data: {e.data}")
            raise
    
    async def wait_for_fork_ready(self, fork_full_name: str, max_attempts: int = 30):
        """Wait for fork to be ready (GitHub operation is async)"""
        for attempt in range(max_attempts):
            try:
                fork = self.github_client.get_repo(fork_full_name)
                # Try to access the default branch to verify fork is ready
                fork.get_branch(fork.default_branch)
                self.logger.info(f"Fork {fork_full_name} is ready")
                return
            except GithubException:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(2)  # Wait 2 seconds between attempts
                else:
                    raise Exception(f"Fork {fork_full_name} not ready after {max_attempts} attempts")
    
    async def sync_fork_with_upstream(
        self, 
        fork: Repository, 
        upstream_repo_name: str,
        branch: str = "main"
    ):
        """Sync fork with upstream repository"""
        try:
            upstream = self.github_client.get_repo(upstream_repo_name)
            
            # Get the latest commit from upstream
            upstream_sha = upstream.get_branch(branch).commit.sha
            
            # Update the fork's branch
            fork_branch = fork.get_branch(branch)
            if fork_branch.commit.sha != upstream_sha:
                self.logger.info(f"Syncing fork {fork.full_name} with upstream {upstream_repo_name}")
                
                # Use GitHub's sync fork API (if available) or merge upstream
                try:
                    # Try to sync using the GitHub API
                    fork.merge_upstream_branch(branch)
                except Exception:
                    # Fallback: create a pull request and merge it
                    self.logger.warning("Direct sync failed, manual sync may be required")
                    
        except GithubException as e:
            self.logger.error(f"Error syncing fork: {e}")
            # Non-fatal error, continue with potentially outdated fork
    
    async def create_branch(
        self, 
        repo: Repository, 
        branch_name: str,
        base_branch: str = "main"
    ) -> Branch:
        """Create a new branch in the repository"""
        try:
            # First, check what branches exist
            branches = list(repo.get_branches())
            self.logger.info(f"Available branches in {repo.full_name}: {[b.name for b in branches]}")
            
            # Try to get the base branch, fallback to default branch if not found
            try:
                base = repo.get_branch(base_branch)
                self.logger.info(f"Using base branch: {base_branch}")
            except GithubException as e:
                if e.status == 404:
                    # Try the repository's default branch
                    default_branch = repo.default_branch
                    self.logger.warning(f"Base branch '{base_branch}' not found, using default branch: {default_branch}")
                    base = repo.get_branch(default_branch)
                    base_branch = default_branch
                else:
                    raise
            
            # Create new branch from base
            ref = repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=base.commit.sha
            )
            
            self.logger.info(f"Created branch {branch_name} from {base_branch} in {repo.full_name}")
            return repo.get_branch(branch_name)
            
        except GithubException as e:
            if e.status == 422 and "Reference already exists" in str(e):
                self.logger.info(f"Branch {branch_name} already exists")
                return repo.get_branch(branch_name)
            else:
                self.logger.error(f"Error creating branch: {e}")
                raise
    
    async def commit_file(
        self,
        repo: Repository,
        branch_name: str,
        file_path: str,
        content: str,
        commit_message: str
    ) -> Dict[str, Any]:
        """Commit a file change to a branch"""
        try:
            # Get the current file (if it exists) to get its SHA
            try:
                current_file = repo.get_contents(file_path, ref=branch_name)
                file_sha = current_file.sha
            except GithubException:
                # File doesn't exist yet
                file_sha = None
            
            # Create or update the file
            if file_sha:
                result = repo.update_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    sha=file_sha,
                    branch=branch_name
                )
            else:
                result = repo.create_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    branch=branch_name
                )
            
            self.logger.info(f"Committed file {file_path} to branch {branch_name}")
            return {
                "commit": result["commit"],
                "content": result["content"]
            }
            
        except GithubException as e:
            self.logger.error(f"Error committing file: {e}")
            raise
    
    async def create_pull_request(
        self,
        base_repo: str,
        base_branch: str,
        head_repo: str,
        head_branch: str,
        title: str,
        body: str
    ) -> Dict[str, Any]:
        """Create a pull request"""
        try:
            # Get the base repository
            base = self.github_client.get_repo(base_repo)
            
            # Create the pull request
            pr = base.create_pull(
                title=title,
                body=body,
                base=base_branch,
                head=f"{head_repo.split('/')[0]}:{head_branch}",
                maintainer_can_modify=True  # Allow maintainers to edit
            )
            
            self.logger.info(f"Created pull request #{pr.number}: {pr.html_url}")
            
            return {
                "number": pr.number,
                "html_url": pr.html_url,
                "title": pr.title,
                "state": pr.state,
                "created_at": pr.created_at.isoformat()
            }
            
        except GithubException as e:
            self.logger.error(f"Error creating pull request: {e}")
            raise
    
    async def create_pr_from_user_account(
        self,
        source_repo: str,  # The upstream repo to fork from (e.g., microsoftdocs/azure-docs-pr)
        file_path: str,
        new_content: str,
        pr_title: str,
        pr_body: str,
        base_branch: str = "main"
    ) -> str:
        """Complete flow to create a PR from user's fork back to the source repository"""
        try:
            self.logger.info(f"Starting PR creation flow for {source_repo}")
            
            # Get username depending on auth method for logging
            if self.auth_method == "github_app":
                username = self.username
            else:
                username = self.user.login
                
            self.logger.info(f"User: {username}, Auth: {self.auth_method}, Source: {source_repo}, File: {file_path}")
            
            # Extract repository name from full path (e.g., "microsoftdocs/azure-docs-pr" -> "azure-docs-pr")
            repo_name = "azure-docs-pr"
            
            # Get username depending on auth method
            if self.auth_method == "github_app":
                username = self.username
            else:
                username = self.user.login
                
            user_fork_name = f"{username}/{repo_name}"
            
            self.logger.info(f"Step 1: Assuming user fork exists at {user_fork_name}")
            
            # 1. Get the user's fork directly (assume it exists)
            fork = self.github_client.get_repo(user_fork_name)
            self.logger.info(f"Step 1: Using existing fork {fork.full_name}")
            
            # TODO: Reintroduce fork management functionality when needed
            # - Check for existing fork
            # - Create fork if it doesn't exist
            # - Sync fork with upstream
            # For now, we assume the fork exists and is reasonably up to date
            
            # 2. Create unique branch name
            timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            branch_name = f"linuxfirst-fix-{timestamp}"
            self.logger.info(f"Step 2: Creating branch {branch_name}")
            
            # 3. Create branch in the user's fork
            await self.create_branch(fork, branch_name, base_branch)
            
            # 4. Commit changes to the user's fork
            self.logger.info(f"Step 3: Committing changes to {file_path}")
            commit_message = f"Fix Linux-first bias in {file_path}"
            await self.commit_file(
                fork,
                branch_name,
                file_path,
                new_content,
                commit_message
            )
            
            # 5. Create pull request from user's fork TO the source repository
            self.logger.info("Step 4: Creating pull request from fork to source")
            pr_result = await self.create_pull_request(
                base_repo=source_repo,  # PR target: the original Microsoft repo
                base_branch=base_branch,
                head_repo=fork.full_name,  # PR source: user's fork
                head_branch=branch_name,
                title=pr_title,
                body=pr_body
            )
            
            self.logger.info(f"PR creation completed successfully: {pr_result['html_url']}")
            return pr_result["html_url"]
            
        except Exception as e:
            self.logger.error(f"Error in PR creation flow: {e}")
            self.logger.error(f"Exception type: {type(e).__name__}")
            if hasattr(e, 'status'):
                self.logger.error(f"HTTP status: {e.status}")
            if hasattr(e, 'data'):
                self.logger.error(f"Error data: {e.data}")
            raise