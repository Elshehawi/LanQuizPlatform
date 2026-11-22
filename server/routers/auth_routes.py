"""Authentication routes: Register and Login for Students and Tutors."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import User
from server.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_or_create_tutor_access_code,
)
from shared.config import EMAIL_DOMAIN_SUFFIX
from shared.schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserRole,
    MessageResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new student or tutor."""
    # Validate email domain
    if not req.email.lower().endswith(EMAIL_DOMAIN_SUFFIX.lower()):
        raise HTTPException(
            status_code=400,
            detail=f"Email must end with {EMAIL_DOMAIN_SUFFIX}",
        )

    # Check if email already exists
    existing = db.query(User).filter(User.email == req.email.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered.")

    # Role-specific validation
    if req.role == UserRole.STUDENT:
        if not req.student_id or not req.student_id.strip():
            raise HTTPException(status_code=400, detail="Student ID is required for students.")
        # Check if student_id already exists
        existing_sid = db.query(User).filter(User.student_id == req.student_id).first()
        if existing_sid:
            raise HTTPException(status_code=409, detail="Student ID already registered.")

    elif req.role == UserRole.TUTOR:
        expected_code = get_or_create_tutor_access_code()
        if not req.tutor_access_code or req.tutor_access_code.strip().upper() != expected_code:
            raise HTTPException(status_code=403, detail="Invalid Tutor Access Code.")

    # Create user
    user = User(
        full_name=req.full_name.strip(),
        email=req.email.lower().strip(),
        password_hash=hash_password(req.password),
        role=req.role.value,
        student_id=req.student_id.strip() if req.student_id else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.role, user.email)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        role=UserRole(user.role),
        full_name=user.full_name,
    )


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Login an existing user."""
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_access_token(user.id, user.role, user.email)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        role=UserRole(user.role),
        full_name=user.full_name,
    )
