"""Attempt routes: start, auto-save, submit with timer enforcement."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Quiz, Question, Attempt, Answer, User
from server.routers._deps import get_current_user_id, require_student
from shared.config import TIMER_GRACE_SECONDS
from shared.schemas import (
    StartAttemptResponse,
    SubmitAttemptRequest,
    DraftSaveRequest,
    AttemptResultOut,
    QuestionOut,
    MessageResponse,
)

router = APIRouter(prefix="/attempts", tags=["attempts"])


def _shuffle_deterministic(items: list, seed: str) -> list:
    """Deterministically shuffle a list based on a seed string."""
    decorated = []
    for i, item in enumerate(items):
        h = hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()
        decorated.append((h, item))
    decorated.sort(key=lambda x: x[0])
    return [item for _, item in decorated]


def _get_shuffled_questions(quiz: Quiz, student_user_id: int) -> list[dict]:
    """Return questions with shuffled order and shuffled MCQ options."""
    seed = f"{student_user_id}:{quiz.id}"
    questions = list(quiz.questions)
    shuffled_qs = _shuffle_deterministic(questions, seed)

    result = []
    for q in shuffled_qs:
        opts = json.loads(q.options_json) if q.options_json else None
        if opts and q.q_type == "MCQ":
            option_seed = f"{seed}:opts:{q.id}"
            opts = _shuffle_deterministic(opts, option_seed)
        result.append(QuestionOut(
            id=q.id,
            q_type=q.q_type,
            prompt=q.prompt,
            options_json=opts,
            points=q.points,
        ))
    return result


@router.post("/start/{quiz_id}", response_model=StartAttemptResponse)
def start_attempt(
    quiz_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_student),
):
    """Start a new quiz attempt. Returns shuffled questions without answers."""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    if not quiz.is_active:
        raise HTTPException(status_code=403, detail="This quiz is not currently active.")

    # Check for existing attempt
    existing = (
        db.query(Attempt)
        .filter(Attempt.quiz_id == quiz_id, Attempt.student_user_id == user_id)
        .first()
    )
    if existing:
        if existing.status in ("PENDING_REVIEW", "GRADED"):
            raise HTTPException(
                status_code=409,
                detail="You have already submitted this quiz.",
            )
        # Resume in-progress attempt
        questions = _get_shuffled_questions(quiz, user_id)
        return StartAttemptResponse(
            attempt_id=existing.id,
            started_at=existing.started_at,
            duration_mins=quiz.duration_mins,
            questions=questions,
        )

    # Create new attempt
    attempt = Attempt(
        quiz_id=quiz_id,
        student_user_id=user_id,
        status="IN_PROGRESS",
    )
    db.add(attempt)
    db.flush()

    # Pre-create empty answer slots
    for q in quiz.questions:
        answer = Answer(
            attempt_id=attempt.id,
            question_id=q.id,
            student_response=None,
            points_awarded=0.0,
            is_graded=False,
        )
        db.add(answer)

    db.commit()
    db.refresh(attempt)

    questions = _get_shuffled_questions(quiz, user_id)
    return StartAttemptResponse(
        attempt_id=attempt.id,
        started_at=attempt.started_at,
        duration_mins=quiz.duration_mins,
        questions=questions,
    )


@router.post("/draft/{attempt_id}", response_model=MessageResponse)
def save_draft(
    attempt_id: int,
    req: DraftSaveRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_student),
):
    """Auto-save draft answers (background call every 10 seconds)."""
    attempt = db.query(Attempt).filter(
        Attempt.id == attempt_id,
        Attempt.student_user_id == user_id,
    ).first()

    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    if attempt.status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Attempt already submitted.")

    for ans_data in req.answers:
        answer = db.query(Answer).filter(
            Answer.attempt_id == attempt_id,
            Answer.question_id == ans_data.question_id,
        ).first()
        if answer:
            answer.student_response = ans_data.student_response

    db.commit()
    return MessageResponse(message="Draft saved.")


@router.post("/submit/{attempt_id}", response_model=AttemptResultOut)
def submit_attempt(
    attempt_id: int,
    req: SubmitAttemptRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_student),
):
    """Submit a quiz attempt. Auto-grades MCQ/TF, marks SHORT for review."""
    attempt = db.query(Attempt).filter(
        Attempt.id == attempt_id,
        Attempt.student_user_id == user_id,
    ).first()

    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    if attempt.status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Attempt already submitted.")

    # Timer enforcement
    quiz = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()
    now = datetime.now(timezone.utc)
    # Handle naive datetimes from SQLite
    started = attempt.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    deadline = started + timedelta(minutes=quiz.duration_mins, seconds=TIMER_GRACE_SECONDS)

    if now > deadline:
        # Auto-grade whatever was saved and lock
        return _auto_grade_and_lock(db, attempt, quiz)

    # Save final answers
    for ans_data in req.answers:
        answer = db.query(Answer).filter(
            Answer.attempt_id == attempt_id,
            Answer.question_id == ans_data.question_id,
        ).first()
        if answer:
            answer.student_response = ans_data.student_response

    db.flush()

    # Grade the attempt
    return _grade_attempt(db, attempt, quiz)


def _grade_attempt(db: Session, attempt: Attempt, quiz: Quiz) -> AttemptResultOut:
    """Grade MCQ/TF immediately, mark SHORT for review."""
    has_short = False
    total_score = 0.0
    max_score = 0.0

    answers = db.query(Answer).filter(Answer.attempt_id == attempt.id).all()
    for answer in answers:
        question = db.query(Question).filter(Question.id == answer.question_id).first()
        if not question:
            continue
        max_score += question.points

        if question.q_type in ("MCQ", "TF"):
            student_resp = (answer.student_response or "").strip().lower()
            correct = question.correct_answer.strip().lower()
            if student_resp == correct:
                answer.points_awarded = question.points
            else:
                answer.points_awarded = 0.0
            answer.is_graded = True
            total_score += answer.points_awarded
        elif question.q_type == "SHORT":
            has_short = True
            answer.is_graded = False

    attempt.submitted_at = datetime.now(timezone.utc)
    if has_short:
        attempt.status = "PENDING_REVIEW"
    else:
        attempt.status = "GRADED"
    attempt.total_score = total_score

    db.commit()

    return AttemptResultOut(
        attempt_id=attempt.id,
        quiz_title=quiz.title,
        status=attempt.status,
        total_score=attempt.total_score,
        max_score=max_score,
        submitted_at=attempt.submitted_at,
    )


def _auto_grade_and_lock(db: Session, attempt: Attempt, quiz: Quiz) -> AttemptResultOut:
    """Auto-grade and lock an attempt that has exceeded the time limit."""
    result = _grade_attempt(db, attempt, quiz)
    return result


@router.get("/my", response_model=list[AttemptResultOut])
def my_attempts(
    db: Session = Depends(get_db),
    user_id: int = Depends(require_student),
):
    """Get all attempts for the current student."""
    attempts = (
        db.query(Attempt)
        .filter(Attempt.student_user_id == user_id)
        .all()
    )
    results = []
    for a in attempts:
        quiz = db.query(Quiz).filter(Quiz.id == a.quiz_id).first()
        max_score = sum(q.points for q in quiz.questions) if quiz else 0
        results.append(AttemptResultOut(
            attempt_id=a.id,
            quiz_title=quiz.title if quiz else "Unknown",
            status=a.status,
            total_score=a.total_score,
            max_score=max_score,
            submitted_at=a.submitted_at,
        ))
    return results
