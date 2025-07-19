"""
GitHub OAuth authentication routes
"""
import secrets
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import httpx
import logging

from shared.utils.database import get_db
from shared.models import User, UserSession
from shared.config import config
from utils.crypto import encrypt_token, decrypt_token
from utils.session import get_session_storage

logger = logging.getLogger(__name__)

router = APIRouter()

# Session storage (Redis or in-memory)
session_storage = get_session_storage()


def generate_session_token() -> str:
    """Generate a secure session token"""
    return secrets.token_urlsafe(32)


def generate_oauth_state() -> str:
    """Generate a secure state parameter for OAuth"""
    return secrets.token_urlsafe(32)


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get the current authenticated user from session"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return None
    
    # Check session storage
    session_data = session_storage.get(session_token)
    if not session_data:
        return None
    
    # Get user from database
    user = db.query(User).filter(User.id == session_data["user_id"]).first()
    if not user:
        return None
    
    # Update last activity
    session_storage.set(session_token, session_data, ttl=86400)  # 24 hours
    
    return user


@router.get("/auth/github/login")
async def github_login(request: Request, redirect: Optional[str] = None):
    """Initiate GitHub OAuth flow"""
    if not config.github_oauth.client_id:
        raise HTTPException(500, "GitHub OAuth not configured")
    
    # Generate and store state
    state = generate_oauth_state()
    session_storage.set(f"oauth_state:{state}", {
        "redirect": redirect or "/",
        "created_at": datetime.utcnow().isoformat()
    }, ttl=600)  # 10 minutes
    
    # Build OAuth URL
    params = {
        "client_id": config.github_oauth.client_id,
        "redirect_uri": config.github_oauth.redirect_uri,
        "scope": config.github_oauth.scopes,
        "state": state
    }
    
    github_auth_url = f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=github_auth_url)


@router.get("/auth/github/callback")
async def github_callback(
    request: Request,
    code: str,
    state: str,
    db: Session = Depends(get_db)
):
    """Handle GitHub OAuth callback"""
    logger.info(f"GitHub OAuth callback received - code: {code[:10]}..., state: {state[:10]}...")
    
    # Verify state
    state_data = session_storage.get(f"oauth_state:{state}")
    if not state_data:
        logger.error(f"Invalid state parameter: {state}")
        raise HTTPException(400, "Invalid state parameter")
    
    logger.info(f"State verified successfully, redirect: {state_data.get('redirect', '/')}")
    
    # Clean up state
    session_storage.delete(f"oauth_state:{state}")
    
    # Exchange code for token
    try:
        async with httpx.AsyncClient() as client:
            logger.info("Exchanging code for access token...")
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": config.github_oauth.client_id,
                    "client_secret": config.github_oauth.client_secret,
                    "code": code,
                    "redirect_uri": config.github_oauth.redirect_uri
                },
                headers={"Accept": "application/json"}
            )
            
            logger.info(f"Token response status: {token_response.status_code}")
            logger.info(f"Token response headers: {dict(token_response.headers)}")
            
            # Check if response is successful
            if token_response.status_code != 200:
                logger.error(f"GitHub token exchange failed with status {token_response.status_code}")
                logger.error(f"Response text: {token_response.text}")
                raise HTTPException(500, "GitHub token exchange failed")
            
            # Try to parse JSON response
            try:
                token_data = token_response.json()
                logger.info(f"Token response parsed successfully, keys: {list(token_data.keys()) if isinstance(token_data, dict) else 'Not a dict'}")
            except Exception as json_error:
                logger.error(f"Failed to parse token response as JSON: {json_error}")
                logger.error(f"Raw response: {token_response.text}")
                raise HTTPException(500, "Invalid response from GitHub token exchange")
            
            # Check for errors in token response
            if isinstance(token_data, dict) and "error" in token_data:
                logger.error(f"GitHub OAuth error: {token_data}")
                raise HTTPException(400, f"OAuth error: {token_data.get('error_description', 'Unknown error')}")
            
            # Extract access token
            if not isinstance(token_data, dict) or "access_token" not in token_data:
                logger.error(f"No access token in response. Response type: {type(token_data)}, content: {token_data}")
                raise HTTPException(500, "No access token received from GitHub")
            
            access_token = token_data["access_token"]
            logger.info(f"Access token received: {access_token[:10]}...")
            
            # Get user info
            logger.info("Fetching user information...")
            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/json"
                }
            )
            
            if user_response.status_code != 200:
                logger.error(f"GitHub user API failed with status {user_response.status_code}")
                logger.error(f"Response text: {user_response.text}")
                raise HTTPException(500, "Failed to fetch user information from GitHub")
            
            try:
                github_user = user_response.json()
                logger.info(f"User info received for: {github_user.get('login', 'unknown')}")
            except Exception as json_error:
                logger.error(f"Failed to parse user response as JSON: {json_error}")
                logger.error(f"Raw user response: {user_response.text}")
                raise HTTPException(500, "Invalid user response from GitHub")
            
            # Validate user data
            if not isinstance(github_user, dict) or "id" not in github_user:
                logger.error(f"Invalid user data structure: {type(github_user)}, content: {github_user}")
                raise HTTPException(500, "Invalid user data from GitHub")
            
            # Get user email if not public
            if not github_user.get("email"):
                logger.info("Fetching user email...")
                email_response = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"token {access_token}",
                        "Accept": "application/json"
                    }
                )
                
                if email_response.status_code == 200:
                    try:
                        emails = email_response.json()
                        if isinstance(emails, list) and len(emails) > 0:
                            primary_email = next((e["email"] for e in emails if isinstance(e, dict) and e.get("primary")), None)
                            github_user["email"] = primary_email
                            logger.info(f"Primary email found: {primary_email}")
                        else:
                            logger.warning("No emails found in response")
                    except Exception as email_error:
                        logger.warning(f"Failed to parse email response: {email_error}")
                else:
                    logger.warning(f"Failed to fetch emails, status: {email_response.status_code}")
    
    except httpx.RequestError as e:
        logger.error(f"GitHub API request failed: {e}")
        raise HTTPException(500, "Failed to communicate with GitHub")
    except Exception as e:
        logger.error(f"Unexpected error during GitHub OAuth: {e}")
        raise HTTPException(500, "OAuth processing failed")
    
    # Create or update user
    try:
        logger.info(f"Creating/updating user for GitHub ID: {github_user['id']}")
        user = db.query(User).filter(User.github_id == github_user["id"]).first()
        if not user:
            logger.info("Creating new user")
            user = User(
                github_id=github_user["id"],
                github_username=github_user["login"],
                email=github_user.get("email"),
                avatar_url=github_user.get("avatar_url")
            )
            db.add(user)
        else:
            logger.info(f"Updating existing user: {user.github_username}")
            # Update user info
            user.github_username = github_user["login"]
            user.email = github_user.get("email")
            user.avatar_url = github_user.get("avatar_url")
            user.last_login = datetime.utcnow()
        
        db.commit()
        db.refresh(user)
        logger.info(f"User saved successfully with ID: {user.id}")
        
        # Create session
        logger.info("Creating user session...")
        session_token = generate_session_token()
        expires_at = datetime.utcnow() + timedelta(days=1)
        
        # Store session in database (optional, for persistence)
        logger.info("Storing session in database...")
        try:
            encrypted_token = encrypt_token(access_token)
            user_session = UserSession(
                user_id=user.id,
                session_token=session_token,
                github_access_token=encrypted_token,
                expires_at=expires_at
            )
            db.add(user_session)
            db.commit()
            logger.info("Session stored in database successfully")
        except Exception as db_error:
            logger.error(f"Failed to store session in database: {db_error}")
            # Continue without database session storage
        
        # Store session in cache
        logger.info("Storing session in cache...")
        try:
            session_storage.set(session_token, {
                "user_id": user.id,
                "github_token": access_token,
                "created_at": datetime.utcnow().isoformat()
            }, ttl=86400)  # 24 hours
            logger.info("Session stored in cache successfully")
        except Exception as cache_error:
            logger.error(f"Failed to store session in cache: {cache_error}")
            raise HTTPException(500, "Failed to create user session")
        
        # Set cookie and redirect
        logger.info(f"Redirecting to: {state_data['redirect']}")
        response = RedirectResponse(url=state_data["redirect"])
        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=config.application.environment == "production",
            max_age=86400  # 24 hours
        )
        
        logger.info("OAuth callback completed successfully")
        return response
        
    except Exception as e:
        logger.error(f"Failed to create/update user or session: {e}")
        db.rollback()
        raise HTTPException(500, "Failed to complete user authentication")


@router.post("/auth/logout")
async def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Log out the current user"""
    session_token = request.cookies.get("session_token")
    if session_token:
        # Remove from cache
        session_storage.delete(session_token)
        
        # Remove from database
        db.query(UserSession).filter(UserSession.session_token == session_token).delete()
        db.commit()
        
        # Clear cookie
        response.delete_cookie("session_token")
    
    return {"success": True}


@router.get("/auth/status")
async def auth_status(current_user: Optional[User] = Depends(get_current_user)):
    """Get current authentication status"""
    if not current_user:
        return {"authenticated": False}
    
    return {
        "authenticated": True,
        "user": {
            "id": current_user.id,
            "username": current_user.github_username,
            "email": current_user.email,
            "avatar_url": current_user.avatar_url
        }
    }


@router.get("/auth/github/config-status")
async def github_config_status():
    """Check GitHub OAuth and App configuration status - useful for debugging"""
    import os
    
    # Check raw environment variables
    raw_env = {
        "GITHUB_CLIENT_ID": os.environ.get("GITHUB_CLIENT_ID", ""),
        "GITHUB_CLIENT_SECRET": os.environ.get("GITHUB_CLIENT_SECRET", ""),
        "GITHUB_OAUTH_REDIRECT_URI": os.environ.get("GITHUB_OAUTH_REDIRECT_URI", ""),
        "GITHUB_OAUTH_SCOPES": os.environ.get("GITHUB_OAUTH_SCOPES", ""),
        "BASE_URL": os.environ.get("BASE_URL", ""),
        "GITHUB_APP_ID": os.environ.get("GITHUB_APP_ID", ""),
        "GITHUB_APP_PRIVATE_KEY": bool(os.environ.get("GITHUB_APP_PRIVATE_KEY", "")),  # Don't expose the key
        "GITHUB_APP_INSTALLATION_URL": os.environ.get("GITHUB_APP_INSTALLATION_URL", "")
    }
    
    # Check parsed configuration
    oauth_config = {
        "client_id": config.github_oauth.client_id,
        "client_secret": bool(config.github_oauth.client_secret),  # Don't expose the secret
        "redirect_uri": config.github_oauth.redirect_uri,
        "scopes": config.github_oauth.scopes
    }
    
    app_config = {
        "app_id": config.github_app.app_id,
        "private_key_configured": bool(config.github_app.private_key),
        "installation_url": config.github_app.installation_url
    }
    
    # Validation checks
    oauth_valid = bool(config.github_oauth.client_id and config.github_oauth.client_secret)
    app_valid = bool(config.github_app.app_id and config.github_app.private_key)
    
    return {
        "oauth": {
            "configured": oauth_valid,
            "config": oauth_config,
            "raw_env_vars": {k: bool(v) if k.endswith("SECRET") or k.endswith("KEY") else v for k, v in raw_env.items() if k.startswith("GITHUB_") and "APP" not in k}
        },
        "github_app": {
            "configured": app_valid,
            "config": app_config,
            "raw_env_vars": {k: bool(v) if k.endswith("KEY") else v for k, v in raw_env.items() if "APP" in k}
        },
        "overall_status": {
            "oauth_ready": oauth_valid,
            "app_ready": app_valid,
            "at_least_one_configured": oauth_valid or app_valid
        }
    }


@router.get("/auth/github/token")
async def get_github_token(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the current user's GitHub access token (for internal API use only)"""
    if not current_user:
        raise HTTPException(401, "Not authenticated")
    
    session_token = request.cookies.get("session_token")
    session_data = session_storage.get(session_token)
    
    if not session_data or "github_token" not in session_data:
        # Try to get from database
        user_session = db.query(UserSession).filter(
            UserSession.user_id == current_user.id,
            UserSession.expires_at > datetime.utcnow()
        ).first()
        
        if not user_session:
            raise HTTPException(401, "No valid session found")
        
        return {"token": decrypt_token(user_session.github_access_token)}
    
    return {"token": session_data["github_token"]}