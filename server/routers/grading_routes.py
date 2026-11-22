"""Grading routes: pending review queue, manual grading, Excel export."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Attempt, Answer, Question, User, Quiz
from server.routers._deps import require_tutor
from server.excel_sync import sync_gradebook_to_excel
from shared.config import GRADEBOOK_PATH
from shared.schemas import (
    PendingAnswerOut,
    GradeAnswerRequest,
    GradeBatchRequest,
    MessageResponse,
    AttemptResultOut,
)

router = APIRouter(prefix="/grading", tags=["grading"])


@router.get("/pending", response_model=list[PendingAnswerOut])
def get_pending_reviews(
    db: Session = Depends(get_db),
    user_id: int = Depends(require_tutor),
):
    """Get all SHORT answers pending review, grouped by quiz/question."""
    pending_answers = (
        db.query(Answer)
        .join(Attempt, Answer.attempt_id == Attempt.id)
        .join(Question, Answer.question_id == Question.id)
        .filter(
            Answer.is_graded == False,
            Question.q_type == "SHORT",
            Attempt.status == "PENDING_REVIEW",
        )
        .all()
    )

    results = []
    for ans in pending_answers:
        attempt = db.query(Attempt).filter(Attempt.id == ans.attempt_id).first()
        question = db.query(Question).filter(Question.id == ans.question_id).first()
        student = db.query(User).filter(User.id == attempt.student_user_id).first()

        results.append(PendingAnswerOut(
            answer_id=ans.id,
            attempt_id=ans.attempt_id,
            student_name=student.full_name if student else "Unknown",
            student_id_str=student.student_id if student else None,
            question_prompt=question.prompt if question else "",
            correct_answer=question.correct_answer if question else "",
            student_response=ans.student_response,
            max_points=question.points if question else 0,
        ))

    return results


@router.post("/grade", response_model=MessageResponse)
def grade_answers(
    req: GradeBatchRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_tutor),
):
    """Grade a batch of SHORT answers."""
    for grade in req.grades:
        answer = db.query(Answer).filter(Answer.id == grade.answer_id).first()
        if not answer:
            raise HTTPException(status_code=404, detail=f"Answer {grade.answer_id} not found.")

        question = db.query(Question).filter(Question.id == answer.question_id).first()
        if grade.points_awarded < 0 or grade.points_awarded > question.points:
            raise HTTPException(
                status_code=400,
                detail=f"Points must be between 0 and {question.points}.",
            )

        answer.points_awarded = grade.points_awarded
        answer.is_graded = True

    db.flush()

    # Check which attempts can now be finalized
    affected_attempt_ids = set(g.answer_id for g in req.grades)
    # Get actual attempt IDs from the answers
    for grade in req.grades:
        answer = db.query(Answer).filter(Answer.id == grade.answer_id).first()
        if answer:
            affected_attempt_ids.add(answer.attempt_id)

    for attempt_id in affected_attempt_ids:
        attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
        if not attempt or attempt.status != "PENDING_REVIEW":
            continue

        # Check if all answers are graded
        all_answers = db.query(Answer).filter(Answer.attempt_id == attempt_id).all()
        if all(a.is_graded for a in all_answers):
            attempt.total_score = sum(a.points_awarded for a in all_answers)
            attempt.status = "GRADED"

    db.commit()
    return MessageResponse(message=f"Graded {len(req.grades)} answer(s) successfully.")


@router.get("/attempts", response_model=list[AttemptResultOut])
def list_all_attempts(
    quiz_id: int | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_tutor),
):
    """List all attempts (optionally filtered by quiz)."""
    query = db.query(Attempt)
    if quiz_id:
        query = query.filter(Attempt.quiz_id == quiz_id)

    attempts = query.all()
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


@router.post("/export-excel", response_model=MessageResponse)
def export_gradebook(
    db: Session = Depends(get_db),
    user_id: int = Depends(require_tutor),
):
    """Export/sync the gradebook to Excel."""
    error = sync_gradebook_to_excel(db, GRADEBOOK_PATH)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return MessageResponse(
        message="Gradebook exported successfully.",
        detail=str(GRADEBOOK_PATH),
    )
