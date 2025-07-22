"""
User feedback API endpoints for bias assessment ratings
"""
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import logging

from shared.utils.database import get_db
from shared.models import UserFeedback, User, Snippet, Page, RewrittenDocument
from routes.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


class FeedbackRequest(BaseModel):
    """Request model for submitting feedback"""
    snippet_id: Optional[int] = Field(None, description="ID of the snippet being rated")
    page_id: Optional[int] = Field(None, description="ID of the page being rated")
    rewritten_document_id: Optional[int] = Field(None, description="ID of the rewritten document being rated")
    rating: str = Field(..., description="Rating: thumbs_up or thumbs_down")
    comment: Optional[str] = Field(None, description="Optional comment for thumbs_down ratings")


class FeedbackResponse(BaseModel):
    """Response model for feedback operations"""
    success: bool
    message: str
    feedback_id: Optional[int] = None


class FeedbackStats(BaseModel):
    """Response model for feedback statistics"""
    total_feedback: int
    thumbs_up: int
    thumbs_down: int
    thumbs_up_percentage: float
    has_comments: int


@router.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Submit feedback for a snippet or page"""
    if not current_user:
        raise HTTPException(401, "Authentication required")
    
    # Validate rating and convert to boolean
    if request.rating not in ['thumbs_up', 'thumbs_down']:
        raise HTTPException(400, "Rating must be 'thumbs_up' or 'thumbs_down'")
    
    # Convert string rating to boolean (True = thumbs_up, False = thumbs_down)
    rating_bool = request.rating == 'thumbs_up'
    
    # Validate that exactly one target type is provided
    target_count = sum([
        request.snippet_id is not None,
        request.page_id is not None,
        request.rewritten_document_id is not None
    ])
    
    if target_count != 1:
        raise HTTPException(400, "Exactly one of snippet_id, page_id, or rewritten_document_id must be provided")
    
    # Verify the target exists and determine target type
    if request.snippet_id:
        target = db.query(Snippet).filter(Snippet.id == request.snippet_id).first()
        if not target:
            raise HTTPException(404, "Snippet not found")
        target_type = "snippet"
        target_id = request.snippet_id
    elif request.page_id:
        target = db.query(Page).filter(Page.id == request.page_id).first()
        if not target:
            raise HTTPException(404, "Page not found")
        target_type = "page"
        target_id = request.page_id
    else:  # rewritten_document_id
        target = db.query(RewrittenDocument).filter(RewrittenDocument.id == request.rewritten_document_id).first()
        if not target:
            raise HTTPException(404, "Rewritten document not found")
        target_type = "rewritten_document"
        target_id = request.rewritten_document_id
    
    try:
        # Check if user already has feedback for this target
        if request.snippet_id:
            existing_feedback = db.query(UserFeedback).filter(
                UserFeedback.user_id == current_user.id,
                UserFeedback.snippet_id == request.snippet_id
            ).first()
        elif request.page_id:
            existing_feedback = db.query(UserFeedback).filter(
                UserFeedback.user_id == current_user.id,
                UserFeedback.page_id == request.page_id
            ).first()
        else:  # rewritten_document_id
            existing_feedback = db.query(UserFeedback).filter(
                UserFeedback.user_id == current_user.id,
                UserFeedback.rewritten_document_id == request.rewritten_document_id
            ).first()
        
        if existing_feedback:
            # Update existing feedback
            existing_feedback.rating = rating_bool
            existing_feedback.comment = request.comment
            existing_feedback.created_at = datetime.utcnow()
            feedback_id = existing_feedback.id
            action = "updated"
        else:
            # Create new feedback
            feedback = UserFeedback(
                user_id=current_user.id,
                snippet_id=request.snippet_id,
                page_id=request.page_id,
                rewritten_document_id=request.rewritten_document_id,
                rating=rating_bool,
                comment=request.comment
            )
            db.add(feedback)
            db.flush()  # Get the ID without committing
            feedback_id = feedback.id
            action = "created"
        
        db.commit()
        
        logger.info(f"Feedback {action} for {target_type} {target_id} by user {current_user.id}")
        
        return FeedbackResponse(
            success=True,
            message=f"Feedback {action} successfully",
            feedback_id=feedback_id
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error submitting feedback: {e}")
        raise HTTPException(500, "Failed to submit feedback")


@router.get("/api/feedback/snippet/{snippet_id}")
async def get_snippet_feedback(
    snippet_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get feedback for a specific snippet"""
    # Verify snippet exists
    snippet = db.query(Snippet).filter(Snippet.id == snippet_id).first()
    if not snippet:
        raise HTTPException(404, "Snippet not found")
    
    # Get user's feedback if authenticated
    user_feedback = None
    if current_user:
        user_feedback = db.query(UserFeedback).filter(
            UserFeedback.user_id == current_user.id,
            UserFeedback.snippet_id == snippet_id
        ).first()
    
    # Get aggregated feedback stats
    all_feedback = db.query(UserFeedback).filter(
        UserFeedback.snippet_id == snippet_id
    ).all()
    
    thumbs_up = sum(1 for f in all_feedback if f.rating == True)
    thumbs_down = sum(1 for f in all_feedback if f.rating == False)
    total = len(all_feedback)
    has_comments = sum(1 for f in all_feedback if f.comment and f.comment.strip())
    
    return {
        "snippet_id": snippet_id,
        "user_feedback": {
            "rating": "thumbs_up" if user_feedback.rating else "thumbs_down" if user_feedback else None,
            "comment": user_feedback.comment if user_feedback else None,
            "created_at": user_feedback.created_at.isoformat() if user_feedback else None
        } if user_feedback else None,
        "stats": {
            "total_feedback": total,
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "thumbs_up_percentage": (thumbs_up / total * 100) if total > 0 else 0,
            "has_comments": has_comments
        }
    }


@router.get("/api/feedback/page/{page_id}")
async def get_page_feedback(
    page_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get feedback for a specific page"""
    # Verify page exists
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")
    
    # Get user's feedback if authenticated
    user_feedback = None
    if current_user:
        user_feedback = db.query(UserFeedback).filter(
            UserFeedback.user_id == current_user.id,
            UserFeedback.page_id == page_id
        ).first()
    
    # Get aggregated feedback stats
    all_feedback = db.query(UserFeedback).filter(
        UserFeedback.page_id == page_id
    ).all()
    
    thumbs_up = sum(1 for f in all_feedback if f.rating == True)
    thumbs_down = sum(1 for f in all_feedback if f.rating == False)
    total = len(all_feedback)
    has_comments = sum(1 for f in all_feedback if f.comment and f.comment.strip())
    
    return {
        "page_id": page_id,
        "user_feedback": {
            "rating": "thumbs_up" if user_feedback.rating else "thumbs_down" if user_feedback else None,
            "comment": user_feedback.comment if user_feedback else None,
            "created_at": user_feedback.created_at.isoformat() if user_feedback else None
        } if user_feedback else None,
        "stats": {
            "total_feedback": total,
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "thumbs_up_percentage": (thumbs_up / total * 100) if total > 0 else 0,
            "has_comments": has_comments
        }
    }


@router.get("/api/feedback/rewritten/{document_id}")
async def get_rewritten_document_feedback(
    document_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get feedback for a specific rewritten document"""
    # Verify rewritten document exists
    document = db.query(RewrittenDocument).filter(RewrittenDocument.id == document_id).first()
    if not document:
        raise HTTPException(404, "Rewritten document not found")
    
    # Get user's feedback if authenticated
    user_feedback = None
    if current_user:
        user_feedback = db.query(UserFeedback).filter(
            UserFeedback.user_id == current_user.id,
            UserFeedback.rewritten_document_id == document_id
        ).first()
    
    # Get aggregated feedback stats
    all_feedback = db.query(UserFeedback).filter(
        UserFeedback.rewritten_document_id == document_id
    ).all()
    
    thumbs_up = sum(1 for f in all_feedback if f.rating == True)
    thumbs_down = sum(1 for f in all_feedback if f.rating == False)
    total = len(all_feedback)
    has_comments = sum(1 for f in all_feedback if f.comment and f.comment.strip())
    
    return {
        "rewritten_document_id": document_id,
        "user_feedback": {
            "rating": "thumbs_up" if user_feedback.rating else "thumbs_down" if user_feedback else None,
            "comment": user_feedback.comment if user_feedback else None,
            "created_at": user_feedback.created_at.isoformat() if user_feedback else None
        } if user_feedback else None,
        "stats": {
            "total_feedback": total,
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "thumbs_up_percentage": (thumbs_up / total * 100) if total > 0 else 0,
            "has_comments": has_comments
        }
    }


@router.get("/api/feedback/stats", response_model=FeedbackStats)
async def get_feedback_stats(
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get overall feedback statistics"""
    # Get all feedback
    all_feedback = db.query(UserFeedback).all()
    
    thumbs_up = sum(1 for f in all_feedback if f.rating == True)
    thumbs_down = sum(1 for f in all_feedback if f.rating == False)
    total = len(all_feedback)
    has_comments = sum(1 for f in all_feedback if f.comment and f.comment.strip())
    
    return FeedbackStats(
        total_feedback=total,
        thumbs_up=thumbs_up,
        thumbs_down=thumbs_down,
        thumbs_up_percentage=(thumbs_up / total * 100) if total > 0 else 0,
        has_comments=has_comments
    )


@router.delete("/api/feedback/snippet/{snippet_id}")
async def delete_feedback(
    snippet_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete user's feedback for a specific snippet"""
    if not current_user:
        raise HTTPException(401, "Authentication required")
    
    # Find user's feedback
    feedback = db.query(UserFeedback).filter(
        UserFeedback.user_id == current_user.id,
        UserFeedback.snippet_id == snippet_id
    ).first()
    
    if not feedback:
        raise HTTPException(404, "Feedback not found")
    
    try:
        db.delete(feedback)
        db.commit()
        
        logger.info(f"Feedback deleted for snippet {snippet_id} by user {current_user.id}")
        
        return {"success": True, "message": "Feedback deleted successfully"}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting feedback: {e}")
        raise HTTPException(500, "Failed to delete feedback")


@router.get("/api/feedback/user/{user_id}")
async def get_user_feedback(
    user_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all feedback by a specific user (admin only or own feedback)"""
    if not current_user:
        raise HTTPException(401, "Authentication required")
    
    # Users can only see their own feedback unless they're admin
    if current_user.id != user_id:
        # TODO: Add admin check here when admin roles are implemented
        raise HTTPException(403, "Access denied")
    
    feedback_list = db.query(UserFeedback).filter(
        UserFeedback.user_id == user_id
    ).all()
    
    return {
        "user_id": user_id,
        "feedback": [
            {
                "id": f.id,
                "snippet_id": f.snippet_id,
                "page_id": f.page_id,
                "rating": "thumbs_up" if f.rating else "thumbs_down",
                "comment": f.comment,
                "created_at": f.created_at.isoformat()
            }
            for f in feedback_list
        ]
    }