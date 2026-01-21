"""
Background task for syncing pull request status with GitHub.

This task polls the GitHub API to:
1. Detect when pending PRs have been submitted (branch turned into actual PR)
2. Update status of open PRs (open → closed/merged)
3. Track merge timestamps
"""
import os
import sys
import re
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
sys.path.insert(0, project_root)

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import requests

from shared.models import PullRequest, User
from shared.utils.database import SessionLocal
from shared.utils.logging import get_logger
from shared.config import config

logger = get_logger(__name__)

# GitHub API configuration
GITHUB_API_BASE = "https://api.github.com"
RATE_LIMIT_BUFFER = 10  # Stop when we have this many requests remaining


class PRSyncService:
    """Service for synchronizing PR records with GitHub API"""

    def __init__(self, github_token: Optional[str] = None):
        """
        Initialize the PR sync service.

        Args:
            github_token: GitHub personal access token for API calls.
                          If not provided, uses GITHUB_SYNC_TOKEN or GITHUB_TOKEN env var.
        """
        # Prefer GITHUB_SYNC_TOKEN (dedicated token with MicrosoftDocs access)
        # Fall back to GITHUB_TOKEN for backwards compatibility
        self.github_token = (
            github_token or
            os.getenv('GITHUB_SYNC_TOKEN') or
            os.getenv('GITHUB_TOKEN')
        )

        if not self.github_token:
            logger.warning("No GitHub token configured for PR sync. Set GITHUB_SYNC_TOKEN with access to target repos.")
        else:
            token_source = 'GITHUB_SYNC_TOKEN' if os.getenv('GITHUB_SYNC_TOKEN') else 'GITHUB_TOKEN'
            logger.debug(f"PR sync using token from {token_source}")

        self.session = requests.Session()
        if self.github_token:
            self.session.headers['Authorization'] = f'token {self.github_token}'
        self.session.headers['Accept'] = 'application/vnd.github.v3+json'
        self.session.headers['User-Agent'] = 'linuxfirst-azuredocs-pr-sync'

    def _check_rate_limit(self) -> bool:
        """
        Check if we have enough API calls remaining.

        Returns:
            True if we can continue, False if we should stop
        """
        try:
            response = self.session.get(f"{GITHUB_API_BASE}/rate_limit")
            if response.status_code == 200:
                data = response.json()
                remaining = data.get('resources', {}).get('core', {}).get('remaining', 0)
                logger.debug(f"GitHub API rate limit remaining: {remaining}")
                return remaining > RATE_LIMIT_BUFFER
        except Exception as e:
            logger.warning(f"Failed to check rate limit: {e}")

        return True  # Continue if we can't check

    def _parse_compare_url(self, compare_url: str) -> Dict[str, str]:
        """
        Parse a GitHub compare URL to extract repo and branch info.

        Args:
            compare_url: URL like https://github.com/owner/repo/compare/main...user:repo:branch?...

        Returns:
            Dict with 'owner', 'repo', 'base_branch', 'head_user', 'head_branch'
        """
        result = {
            'owner': None,
            'repo': None,
            'base_branch': None,
            'head_user': None,
            'head_branch': None
        }

        try:
            # Remove query params
            url_path = compare_url.split('?')[0]

            # Match pattern: /owner/repo/compare/base...head_user:head_repo:head_branch
            match = re.search(
                r'github\.com/([^/]+)/([^/]+)/compare/([^.]+)\.\.\.([^:]+):([^:]+):(.+)$',
                url_path
            )

            if match:
                result['owner'] = match.group(1)
                result['repo'] = match.group(2)
                result['base_branch'] = match.group(3)
                result['head_user'] = match.group(4)
                result['head_branch'] = match.group(6)  # Skip head_repo (group 5)

        except Exception as e:
            logger.warning(f"Failed to parse compare URL {compare_url}: {e}")

        return result

    def _find_pr_for_branch(
        self,
        owner: str,
        repo: str,
        head_user: str,
        head_branch: str
    ) -> Optional[Dict[str, Any]]:
        """
        Find an open or recently closed PR for a specific branch.

        Args:
            owner: Repository owner
            repo: Repository name
            head_user: User who owns the head branch
            head_branch: Name of the head branch

        Returns:
            PR data dict if found, None otherwise
        """
        try:
            # Search for PRs with matching head branch
            # Format: user:branch
            head = f"{head_user}:{head_branch}"

            # First check open PRs
            response = self.session.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
                params={
                    'head': head,
                    'state': 'all',  # Check both open and closed
                    'per_page': 5
                }
            )

            if response.status_code == 200:
                prs = response.json()
                if prs:
                    return prs[0]  # Return the most recent

        except Exception as e:
            logger.warning(f"Failed to find PR for {head_user}:{head_branch}: {e}")

        return None

    def sync_pending_prs(self, db: Session, limit: int = 50) -> int:
        """
        Check pending PRs to see if they've been submitted to GitHub.

        Args:
            db: Database session
            limit: Maximum number of PRs to check

        Returns:
            Number of PRs updated
        """
        updated_count = 0

        # Get pending PRs that haven't been synced recently (within last hour)
        cutoff = datetime.utcnow() - timedelta(hours=1)
        pending_prs = db.query(PullRequest).filter(
            PullRequest.status == 'pending',
            or_(
                PullRequest.last_synced_at.is_(None),
                PullRequest.last_synced_at < cutoff
            )
        ).limit(limit).all()

        logger.info(f"Checking {len(pending_prs)} pending PRs for submission")

        for pr in pending_prs:
            if not self._check_rate_limit():
                logger.warning("Rate limit reached, stopping sync")
                break

            # Parse the compare URL to get branch info
            url_info = self._parse_compare_url(pr.compare_url)

            if not all([url_info['owner'], url_info['repo'], url_info['head_branch']]):
                logger.warning(f"Could not parse compare URL for PR {pr.id}: {pr.compare_url}")
                pr.last_synced_at = datetime.utcnow()
                continue

            # Look for a PR matching this branch
            gh_pr = self._find_pr_for_branch(
                url_info['owner'],
                url_info['repo'],
                url_info['head_user'],
                url_info['head_branch']
            )

            if gh_pr:
                # Update PR record with GitHub data
                pr.pr_url = gh_pr.get('html_url')
                pr.pr_number = gh_pr.get('number')
                pr.pr_title = gh_pr.get('title')
                pr.pr_state = gh_pr.get('state')
                pr.submitted_at = datetime.fromisoformat(
                    gh_pr.get('created_at', '').replace('Z', '+00:00')
                ).replace(tzinfo=None) if gh_pr.get('created_at') else None

                # Update status based on GitHub state
                if gh_pr.get('merged_at'):
                    pr.status = 'merged'
                    pr.merged_at = datetime.fromisoformat(
                        gh_pr['merged_at'].replace('Z', '+00:00')
                    ).replace(tzinfo=None)
                    pr.closed_at = pr.merged_at
                elif gh_pr.get('state') == 'closed':
                    pr.status = 'closed'
                    pr.closed_at = datetime.fromisoformat(
                        gh_pr.get('closed_at', '').replace('Z', '+00:00')
                    ).replace(tzinfo=None) if gh_pr.get('closed_at') else None
                else:
                    pr.status = 'open'

                updated_count += 1
                logger.info(f"PR {pr.id} found on GitHub: #{pr.pr_number} ({pr.status})")

            pr.last_synced_at = datetime.utcnow()

        db.commit()
        return updated_count

    def sync_open_prs(self, db: Session, limit: int = 50) -> int:
        """
        Update status of open PRs.

        Args:
            db: Database session
            limit: Maximum number of PRs to check

        Returns:
            Number of PRs updated
        """
        updated_count = 0

        # Get open PRs that haven't been synced recently (within last 30 minutes)
        cutoff = datetime.utcnow() - timedelta(minutes=30)
        open_prs = db.query(PullRequest).filter(
            PullRequest.status == 'open',
            PullRequest.pr_number.isnot(None),
            or_(
                PullRequest.last_synced_at.is_(None),
                PullRequest.last_synced_at < cutoff
            )
        ).limit(limit).all()

        logger.info(f"Checking {len(open_prs)} open PRs for status updates")

        for pr in open_prs:
            if not self._check_rate_limit():
                logger.warning("Rate limit reached, stopping sync")
                break

            if not pr.pr_url or not pr.pr_number:
                pr.last_synced_at = datetime.utcnow()
                continue

            # Parse owner/repo from pr_url
            match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr.pr_url)
            if not match:
                pr.last_synced_at = datetime.utcnow()
                continue

            owner, repo, _ = match.groups()

            try:
                response = self.session.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr.pr_number}"
                )

                if response.status_code == 200:
                    gh_pr = response.json()

                    # Update title if changed
                    if gh_pr.get('title') != pr.pr_title:
                        pr.pr_title = gh_pr.get('title')

                    pr.pr_state = gh_pr.get('state')

                    # Check for merge/close
                    if gh_pr.get('merged_at'):
                        pr.status = 'merged'
                        pr.merged_at = datetime.fromisoformat(
                            gh_pr['merged_at'].replace('Z', '+00:00')
                        ).replace(tzinfo=None)
                        pr.closed_at = pr.merged_at
                        updated_count += 1
                        logger.info(f"PR {pr.id} (#{pr.pr_number}) was merged")
                    elif gh_pr.get('state') == 'closed':
                        pr.status = 'closed'
                        pr.closed_at = datetime.fromisoformat(
                            gh_pr.get('closed_at', '').replace('Z', '+00:00')
                        ).replace(tzinfo=None) if gh_pr.get('closed_at') else None
                        updated_count += 1
                        logger.info(f"PR {pr.id} (#{pr.pr_number}) was closed without merge")

                elif response.status_code == 404:
                    # PR no longer exists
                    pr.status = 'closed'
                    updated_count += 1
                    logger.warning(f"PR {pr.id} (#{pr.pr_number}) not found on GitHub, marking as closed")

            except Exception as e:
                logger.error(f"Error fetching PR {pr.id}: {e}")

            pr.last_synced_at = datetime.utcnow()

        db.commit()
        return updated_count

    def run_full_sync(self, db: Optional[Session] = None) -> Dict[str, int]:
        """
        Run a full sync of all PR records.

        Args:
            db: Optional database session (creates one if not provided)

        Returns:
            Dict with sync statistics
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            logger.info("Starting full PR sync...")

            stats = {
                'pending_checked': 0,
                'pending_updated': 0,
                'open_checked': 0,
                'open_updated': 0
            }

            # Sync pending PRs
            stats['pending_updated'] = self.sync_pending_prs(db)

            # Sync open PRs
            stats['open_updated'] = self.sync_open_prs(db)

            logger.info(
                f"PR sync complete: {stats['pending_updated']} pending PRs updated, "
                f"{stats['open_updated']} open PRs updated"
            )

            return stats

        finally:
            if close_db:
                db.close()


def run_pr_sync():
    """Entry point for running PR sync as a standalone task"""
    logger.info("PR sync task starting...")

    sync_service = PRSyncService()
    stats = sync_service.run_full_sync()

    logger.info(f"PR sync complete: {stats}")
    return stats


if __name__ == '__main__':
    run_pr_sync()
