"""
GitHubService - Handles GitHub repository scanning functionality
Extracted from the monolithic queue_worker.py
"""
import os
import re
import time
import random
import json
from typing import List, Dict, Optional, Tuple
from github import Github
from github.Repository import Repository
from github.GithubException import UnknownObjectException
from shared.config import config
from shared.utils.logging import get_logger



class GitHubService:
    """Service responsible for GitHub repository scanning operations"""
    
    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or os.environ.get('GITHUB_TOKEN')
        if not self.github_token:
            raise ValueError("GITHUB_TOKEN not set in environment. Cannot scan GitHub repo.")
        
        self.github_client = Github(self.github_token)
        self.logger = get_logger(__name__)
        self._repo_cache: Dict[str, Repository] = {}

    def _check_rate_limit(self):
        """
        Check GitHub API rate limit from response headers and pause if necessary to avoid 429 errors
        """
        try:
            # Get rate limit info from response headers (no API call needed)
            remaining, limit = self.github_client.rate_limiting
            
            # If no rate limit info available yet, continue (first API call will populate it)
            if remaining == -1:
                return
            
            # Log rate limit status periodically (every 100 calls)
            if remaining % 100 == 0:
                self.logger.info(f"GitHub API rate limit: {remaining}/{limit} remaining")
            
            # Pause if we're close to the limit
            if remaining < 100:  # Safety buffer
                reset_time = self.github_client.rate_limiting_resettime
                current_time = time.time()
                sleep_time = reset_time - current_time + 60  # Extra 60s buffer
                if sleep_time > 0:
                    self.logger.warning(f"Rate limit approaching ({remaining} remaining), pausing for {sleep_time:.0f} seconds until reset")
                    time.sleep(sleep_time)
                    self.logger.info("Rate limit reset, resuming operations")
                    
        except Exception as e:
            # Don't let rate limit checking break the actual operation
            self.logger.warning(f"Could not check rate limit: {e}")

    def _get_cached_repo(self, repo_full_name: str):
        """
        Get a Repository object, using cache to avoid redundant API calls.

        Args:
            repo_full_name: GitHub repository in format 'owner/repo'

        Returns:
            PyGithub Repository object
        """
        if repo_full_name not in self._repo_cache:
            self._repo_cache[repo_full_name] = self.github_client.get_repo(repo_full_name)
        return self._repo_cache[repo_full_name]

    def parse_github_url(self, url: str) -> Optional[Dict[str, str]]:
        """
        Parse GitHub repository URL to extract repo name, branch, and path
        
        Args:
            url: GitHub repository URL
            
        Returns:
            Dictionary with repo_full_name, branch, and path, or None if invalid
        """
        match = re.match(r'https://github.com/([^/]+/[^/]+)(/tree/[^/]+(/.*)?)?', url)
        if not match:
            return None
            
        repo_full_name = match.group(1)
        path = match.group(3) or ''
        
        # Extract branch from URL
        branch = 'main'  # default
        if '/tree/' in url:
            branch_match = re.search(r'/tree/([^/]+)', url)
            if branch_match:
                branch = branch_match.group(1)
                
        return {
            'repo_full_name': repo_full_name,
            'branch': branch,
            'path': path
        }

    def is_windows_focused_url(self, url: str) -> bool:
        """Check if URL appears to be Windows-focused"""
        url = url.lower()
        return (
            'windows' in url or
            '/powershell/' in url or
            '/cmd/' in url or
            '/cli-windows/' in url
        )

    def is_windows_focused_content(self, content: str) -> bool:
        """Check if markdown content appears to be Windows-focused"""
        h1_match = re.search(r'^# (.+)$', content, re.MULTILINE)
        if h1_match and 'powershell' in h1_match.group(1).lower():
            return True
        return False

    def list_markdown_files(
        self, 
        repo_full_name: str, 
        path: str, 
        branch: str,
        max_files: Optional[int] = None,
        max_dirs: int = 100,
        progress_file: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        List all markdown files in a GitHub repository path
        
        Args:
            repo_full_name: GitHub repository in format 'owner/repo'
            path: Path within repository to scan
            branch: Branch to scan
            max_files: Maximum number of files to return (None = unlimited)
            max_dirs: Maximum number of directories to process
            progress_file: Optional file to save/restore progress
            
        Returns:
            List of dictionaries with 'path' and 'sha' keys
        """
        repo = self._get_cached_repo(repo_full_name)
        
        files = []
        dirs_to_process = [path]
        dirs_seen = 0
        processed_dirs = set()
        
        # Load progress if file exists
        if progress_file and os.path.exists(progress_file):
            try:
                with open(progress_file, 'r') as pf:
                    state = json.load(pf)
                    files = state.get('files', [])
                    dirs_to_process = state.get('dirs_to_process', [path])
                    dirs_seen = state.get('dirs_seen', 0)
                    processed_dirs = set(state.get('processed_dirs', []))
                print(f"[DEBUG] Resuming from progress file: {progress_file}")
            except Exception as e:
                print(f"[ERROR] Failed to load progress file: {e}")
                
        min_delay = 0.5
        max_delay = 2.0
        
        while dirs_to_process and (max_files is None or len(files) < max_files) and dirs_seen < max_dirs:
            current_dir = dirs_to_process.pop(0)
            
            if current_dir in processed_dirs:
                print(f"[DEBUG] Skipping already processed directory: {current_dir}")
                dirs_seen += 1
                continue
                
            print(f"[DEBUG] Fetching contents of: {current_dir}")
            
            try:
                contents = repo.get_contents(current_dir, ref=branch)
            except Exception as e:
                print(f"[ERROR] Exception in get_contents for {current_dir}: {e}")
                # Exponential backoff on error
                delay = min(max_delay, min_delay * (2 ** dirs_seen))
                print(f"[DEBUG] Sleeping for {delay:.2f}s before retrying...")
                time.sleep(delay)
                continue
                
            dirs_seen += 1
            processed_dirs.add(current_dir)
            
            for content_file in contents:
                if content_file.type == 'dir':
                    dirs_to_process.append(content_file.path)
                elif content_file.path.endswith('.md'):
                    files.append({
                        'path': content_file.path,
                        'sha': content_file.sha
                    })
                    if max_files is not None and len(files) >= max_files:
                        print(f"[DEBUG] Reached max_files={max_files}")
                        break
                        
            # Save progress
            if progress_file:
                try:
                    with open(progress_file, 'w') as pf:
                        json.dump({
                            'files': files,
                            'dirs_to_process': dirs_to_process,
                            'dirs_seen': dirs_seen,
                            'processed_dirs': list(processed_dirs)
                        }, pf)
                except Exception as e:
                    print(f"[ERROR] Failed to write progress file: {e}")
                    
            # Rate limiting delay
            delay = random.uniform(min_delay, max_delay)
            print(f"[DEBUG] Sleeping for {delay:.2f}s to avoid rate limiting...")
            time.sleep(delay)
            
        print(f"[DEBUG] Total .md files found: {len(files)}")
        return files

    def get_file_content(self, repo_full_name: str, file_path: str, branch: str) -> Optional[str]:
        """
        Get content of a specific file from GitHub repository with rate limit management
        
        Args:
            repo_full_name: GitHub repository in format 'owner/repo'
            file_path: Path to file within repository
            branch: Branch to get file from
            
        Returns:
            File content as string, or None if error
        """
        try:
            # Check rate limit before making API call
            self._check_rate_limit()
            
            repo = self._get_cached_repo(repo_full_name)
            file_content_obj = repo.get_contents(file_path, ref=branch)
            
            # Rate limit info is now updated from the API response headers
            return file_content_obj.decoded_content.decode()
        except Exception as e:
            print(f"[ERROR] Could not fetch file {file_path}: {e}")
            return None

    def extract_code_blocks(self, markdown_content: str) -> List[str]:
        """
        Extract code blocks from markdown content
        
        Args:
            markdown_content: Markdown file content
            
        Returns:
            List of code block contents
        """
        return re.findall(r'```(?:[a-zA-Z0-9]*)\n(.*?)```', markdown_content, re.DOTALL)

    def generate_github_url(self, repo_full_name: str, branch: str, file_path: str) -> str:
        """Generate GitHub blob URL for a file"""
        # Strip leading slash from file_path to avoid double slashes
        file_path = file_path.lstrip('/')
        return f"https://github.com/{repo_full_name}/blob/{branch}/{file_path}"

    def get_file_metadata(self, repo_full_name: str, file_path: str, branch: str) -> Optional[Dict[str, str]]:
        """
        Get metadata for a GitHub file including SHA and last modified date
        
        Args:
            repo_full_name: GitHub repository in format 'owner/repo'
            file_path: Path to file within repository
            branch: Branch to get metadata from
            
        Returns:
            Dictionary with 'sha', 'last_modified', and 'path' keys, or None if error
        """
        try:
            # Check rate limit before making API calls
            self._check_rate_limit()
            
            repo = self._get_cached_repo(repo_full_name)
            file_obj = repo.get_contents(file_path, ref=branch)
            
            # Get commit info for last modified date
            commits = repo.get_commits(path=file_path, sha=branch)
            last_commit = commits[0] if commits.totalCount > 0 else None
            last_modified = last_commit.commit.committer.date if last_commit else None
            
            return {
                'sha': file_obj.sha,
                'last_modified': last_modified.isoformat() if last_modified else None,
                'path': file_path,
                'size': file_obj.size
            }
        except Exception as e:
            print(f"[ERROR] Could not fetch metadata for file {file_path}: {e}")
            return None

    def has_file_changed(self, repo_full_name: str, file_path: str, branch: str, current_sha: str) -> bool:
        """
        Check if a GitHub file has changed by comparing SHA values
        
        Args:
            repo_full_name: GitHub repository in format 'owner/repo'
            file_path: Path to file within repository
            branch: Branch to check
            current_sha: Current SHA to compare against
            
        Returns:
            True if file has changed, False if unchanged, None if error
        """
        metadata = self.get_file_metadata(repo_full_name, file_path, branch)
        if not metadata:
            return None
            
        return metadata['sha'] != current_sha

    def get_head_commit(self, repo_full_name: str, branch: str) -> Tuple[Optional[str], bool]:
        """
        Get the HEAD commit SHA for a repository branch

        Args:
            repo_full_name: GitHub repository in format 'owner/repo'
            branch: Branch to get HEAD commit from

        Returns:
            Tuple of (HEAD commit SHA or None, is_not_found)
            - (sha, False) on success
            - (None, True) if repo not found (404)
            - (None, False) on other errors
        """
        try:
            repo = self._get_cached_repo(repo_full_name)
            branch_obj = repo.get_branch(branch)
            return branch_obj.commit.sha, False
        except UnknownObjectException as e:
            print(f"[ERROR] Could not get HEAD commit for {repo_full_name}:{branch}: {e}")
            return None, True  # 404 - repo not found
        except Exception as e:
            print(f"[ERROR] Could not get HEAD commit for {repo_full_name}:{branch}: {e}")
            return None, False  # Other error

    def compare_commits(self, repo_full_name: str, base_sha: str, head_sha: str):
        """
        Compare two commits using GitHub Compare API
        
        Args:
            repo_full_name: GitHub repository in format 'owner/repo'
            base_sha: Base commit SHA
            head_sha: Head commit SHA
            
        Returns:
            GitHub comparison object or None if error
        """
        try:
            repo = self._get_cached_repo(repo_full_name)
            comparison = repo.compare(base_sha, head_sha)
            return comparison
        except Exception as e:
            print(f"[ERROR] Could not compare commits {base_sha}...{head_sha}: {e}")
            return None

    def get_tree(self, repo_full_name: str, sha: str, path: str = '', recursive: bool = True):
        """
        Get repository tree using GitHub Trees API
        
        Args:
            repo_full_name: GitHub repository in format 'owner/repo'
            sha: Tree SHA (usually commit SHA)
            path: Path within repository to get tree for
            recursive: Whether to get tree recursively
            
        Returns:
            GitHub tree object or None if error
        """
        try:
            repo = self._get_cached_repo(repo_full_name)
            if path:
                # Get tree for specific path
                contents = repo.get_contents(path, ref=sha)
                
                # Handle case where contents is a list (directory) or single object (file)
                if isinstance(contents, list):
                    # Path points to a directory, get the first item which should be the directory itself
                    # Actually, we need to find the directory entry in the parent's tree
                    # For now, let's get the tree directly from the path
                    try:
                        # Get the directory tree by finding it in the parent tree
                        path_parts = path.strip('/').split('/')
                        current_tree = repo.get_git_tree(sha, recursive=False)
                        
                        # Navigate to the target directory
                        for part in path_parts:
                            for item in current_tree.tree:
                                if item.path == part and item.type == 'tree':
                                    current_tree = repo.get_git_tree(item.sha, recursive=recursive)
                                    break
                            else:
                                # Path not found
                                return None
                        return current_tree
                    except Exception:
                        return None
                elif contents.type == 'dir':
                    tree = repo.get_git_tree(contents.sha, recursive=recursive)
                    return tree
                else:
                    return None
            else:
                # Get root tree
                commit = repo.get_commit(sha)
                tree = repo.get_git_tree(commit.commit.tree.sha, recursive=recursive)
                return tree
        except Exception as e:
            print(f"[ERROR] Could not get tree for {repo_full_name}:{sha} at path '{path}': {e}")
            return None