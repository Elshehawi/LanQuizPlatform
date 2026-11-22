"""Shared FastAPI dependencies for authentication."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from server.database import get_db
from server.auth import decode_access_token
from server.models import User

security = HTTPBearer()


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """Extract and validate user ID from JWT token."""
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    return int(payload["sub"])


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Get the full user object from JWT token."""
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    return user


def require_tutor(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """Require the current user to be a Tutor. Returns user_id."""
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    if payload.get("role") != "TUTOR":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tutor access required.",
        )
    return int(payload["sub"])


def require_student(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """Require the current user to be a Student. Returns user_id."""
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    if payload.get("role") != "STUDENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student access required.",
        )
    return int(payload["sub"])
