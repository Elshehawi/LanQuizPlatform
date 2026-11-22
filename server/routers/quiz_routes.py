"""Quiz & question CRUD, active quiz fetch (without answers)."""

from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.database import get_db
from server.auth import decode_access_token
from server.models import Quiz, Question
from shared.config import DEFAULT_COURSE_ID
from shared.schemas import (
    QuizCreate,
    QuizOut,
    QuizDetailOut,
    QuestionOut,
    QuizToggleRequest,
    MessageResponse,
    UserRole,
)

from server.routers._deps import get_current_user_id, require_tutor

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.post("/", response_model=QuizOut, status_code=status.HTTP_201_CREATED)
def create_quiz(
    req: QuizCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_tutor),
):
    """Create a new quiz with questions (Tutor only)."""
    # Check for duplicate quiz_number in course
    existing = (
        db.query(Quiz)
        .filter(Quiz.course_id == DEFAULT_COURSE_ID, Quiz.quiz_number == req.quiz_number)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Quiz number {req.quiz_number} already exists for this course.",
        )

    quiz = Quiz(
        course_id=DEFAULT_COURSE_ID,
        quiz_number=req.quiz_number,
        title=req.title,
        duration_mins=req.duration_mins,
        is_active=False,
    )
    db.add(quiz)
    db.flush()

    for q in req.questions:
        options = json.dumps(q.options_json) if q.options_json else None
        question = Question(
            quiz_id=quiz.id,
            q_type=q.q_type.value,
            prompt=q.prompt,
            options_json=options,
            correct_answer=q.correct_answer,
            points=q.points,
        )
        db.add(question)

    db.commit()
    db.refresh(quiz)

    return QuizOut(
        id=quiz.id,
        title=quiz.title,
        quiz_number=quiz.quiz_number,
        duration_mins=quiz.duration_mins,
        is_active=quiz.is_active,
        created_at=quiz.created_at,
        question_count=len(req.questions),
    )


@router.get("/", response_model=list[QuizOut])
def list_quizzes(
    active_only: bool = False,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """List all quizzes (optionally only active ones)."""
    query = db.query(Quiz).filter(Quiz.course_id == DEFAULT_COURSE_ID)
    if active_only:
        query = query.filter(Quiz.is_active == True)
    quizzes = query.order_by(Quiz.quiz_number).all()
    return [
        QuizOut(
            id=q.id,
            title=q.title,
            quiz_number=q.quiz_number,
            duration_mins=q.duration_mins,
            is_active=q.is_active,
            created_at=q.created_at,
            question_count=len(q.questions),
        )
        for q in quizzes
    ]


@router.get("/{quiz_id}", response_model=QuizDetailOut)
def get_quiz(
    quiz_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Get quiz with questions (without correct answers for students)."""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")

    questions = []
    for q in quiz.questions:
        opts = json.loads(q.options_json) if q.options_json else None
        questions.append(QuestionOut(
            id=q.id,
            q_type=q.q_type,
            prompt=q.prompt,
            options_json=opts,
            points=q.points,
        ))

    return QuizDetailOut(
        id=quiz.id,
        title=quiz.title,
        quiz_number=quiz.quiz_number,
        duration_mins=quiz.duration_mins,
        is_active=quiz.is_active,
        questions=questions,
    )


@router.patch("/{quiz_id}/toggle", response_model=MessageResponse)
def toggle_quiz(
    quiz_id: int,
    req: QuizToggleRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_tutor),
):
    """Activate or deactivate a quiz (Tutor only)."""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")

    quiz.is_active = req.is_active
    db.commit()
    state = "activated" if req.is_active else "deactivated"
    return MessageResponse(message=f"Quiz '{quiz.title}' {state}.")


@router.delete("/{quiz_id}", response_model=MessageResponse)
def delete_quiz(
    quiz_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_tutor),
):
    """Delete a quiz (Tutor only)."""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")

    db.delete(quiz)
    db.commit()
    return MessageResponse(message=f"Quiz '{quiz.title}' deleted.")
